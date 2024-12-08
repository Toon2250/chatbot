import streamlit as st
import os
from crewai import Agent, Task, Crew, LLM
from crewai_tools import PDFSearchTool
from chromadb import PersistentClient
from chromadb.config import DEFAULT_TENANT, DEFAULT_DATABASE, Settings
from sentence_transformers import SentenceTransformer
from crewai.memory import ShortTermMemory, LongTermMemory
import openai

# Some code couldn't be found in the libraries, even though it was mentioned on the official documentation

class EnhanceLongTermMemory(LongTermMemory):
    def __init__(self, storage):
        self.storage = storage

    def add_to_memory(self, documents, metadatas, ids):
        self.storage.store(documents, metadatas, ids)

    def retrieve_from_memory(self, query, top_k=5):
        return self.storage.fetch_relevant(query, top_k=top_k)

class EnhanceShortTermMemory(ShortTermMemory):
    def __init__(self, storage):
        self.storage = storage
        self.memory = []  # Internal memory cache for fast retrieval during the session

    def add_to_memory(self, documents, metadatas, ids):
        # Update the internal cache
        self.memory.extend(zip(documents, metadatas, ids))
        
        # Store in ChromaDB
        self.storage.store(documents, metadatas, ids)

    def retrieve_from_memory(self, query, top_k=5):
        # Retrieve from ChromaDB
        relevant_docs = self.storage.fetch_relevant(query, top_k=top_k)
        return relevant_docs

    def clear_memory(self):
        # Clear the cache
        self.memory = []

        # Clearing ChromaDB collection (reinitialize the collection)
        self.storage.collection.delete()  # Assuming ChromaDB supports this method
        self.storage.collection = initialize_chromadb("short_term")

# Prepare for usage of vectorized pdf's

def initialize_chromadb(collection_name):
    client = PersistentClient(
        path="./vector_db",
        settings=Settings(),
        tenant=DEFAULT_TENANT,
        database=DEFAULT_DATABASE
    )

    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        collection = client.create_collection(name=collection_name)

    return collection

class ChromaDBStorage:
    def __init__(self, collection, openai_api_key):
        self.collection = collection
        self.openai_api_key = openai_api_key

    def fetch_relevant(self, query, top_k=5):
        query_embedding = self._get_openai_embedding(query)
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=top_k
        )
        return results["documents"]

    def store(self, documents, metadatas, ids):
        embeddings = [self._get_openai_embedding(doc) for doc in documents]
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
            embeddings=embeddings
        )
    
    def _get_openai_embedding(self, text):
        openai.api_key = self.openai_api_key
        response = openai.Embedding.create(
            input=text,
            model="text-embedding-ada-002"
        )
        return response['data'][0]['embedding']

# Talk to Groq 
if "api_key" not in st.session_state:
    st.session_state.api_key = None  # Initialize API key in session state

if "openai_api_key" not in st.session_state:
    st.session_state.openai_api_key = None

try:
    llm = LLM(
    model="llama3-70b-8192",
    temperature=0.7,
    base_url="https://api.groq.com/openai/v1",
    api_key=st.session_state.api_key
    )
except Exception as e:
    st.error(f"Error initializing ChatGroq: {e}")

# needed for pdf-uploads
UPLOAD_FOLDER = "./pdfs"

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

Question_Identifier = Agent(
        role='Question_Identifier_Agent',
        goal="""You identify what the question is and you add other parts which is needed to answer the question.""",
        backstory="""You are an expert in understanding and defining questions. 
            Your goal is to extract a clear, concise questio, statements from the user's input.""",
        verbose=True,
        allow_delegation=False,
        llm=llm,
    )

Question_Solving = Agent(
        role='Question_Solving_Agent',
        goal="""You solve the questions.""",
        backstory="""You are an expert in understanding and solving questions. 
            Your goal is to answer the questions in a clear, concise statement from the input, 
            ensuring the answers is clear.""",
        verbose=True,
        allow_delegation=False,
        llm=llm,
    )

BramBot = Agent(
        role='Summerazing_Agent',
        goal="""Summerize the solved question, in a clear way. If the question is about AI, DL, NLP you add ab interesting tidbit about the topic""",
        backstory="""You are a helpful assistant called BramBot, and you are very passionate about Artificial intelligence,
        Deep Learning and Natural language processing. You also like coffee, never call it a cup of joe.
        You also like giving some interesting tidbits about AI, DL, NLP wich have something to do with the topic.""",
        verbose=True,
        allow_delegation=False,
        llm=llm,
    )


# Title and app description
st.title("💬 BramBot")
st.write(
    "This is a chatbot that uses Groq's powerful models to generate responses. "
    "To use this app, simply enter your message below and get an instant response from Groq's AI."
)
st.session_state.api_key = st.text_input(
    "Enter your Groq API Key:",  # Input prompt
    value=st.session_state.api_key or "",  # Pre-fill if previously entered
    type="password",  # Hide input for security
    placeholder="Your API Key here"  # Placeholder for guidance
)
st.session_state.openai_api_key = st.text_input(
    "Enter your Openai API Key:",  # Input prompt
    value=st.session_state.openai_api_key or "",  # Pre-fill if previously entered
    type="password",  # Hide input for security
    placeholder="Your API Key here"  # Placeholder for guidance
)

pdf_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(".pdf")]
toggle_dropdown = st.checkbox("Enable file selection")

if "selected_file" not in st.session_state:
    st.session_state.selected_file = None

if toggle_dropdown and pdf_files:
    st.session_state.selected_file = st.selectbox(
        "Select a PDF file to view or process",
        pdf_files,
        key="dropdown"
    )
else:
    st.session_state.selected_file = None

if st.session_state.selected_file:
    st.write(f"You selected: {st.session_state.selected_file}")
    file_path = os.path.join(UPLOAD_FOLDER, st.session_state.selected_file)

# Step 5: Chatbot functionality
# Initialize the chat history if not already done
if "messages" not in st.session_state:
    st.session_state.messages = []  # Stores user and bot messages

# Display previous chat messages in the app
for message in st.session_state.messages:
    with st.chat_message(message["role"]):  # Display messages as user or assistant
        st.markdown(message["content"])

# Input field for user messages
user_input = st.chat_input("What do you want to ask the bot?")  # Input box for user queries

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    # getting acces to memory
    openai_api_key = st.session_state.openai_api_key
    long_term_collection = initialize_chromadb("long_term")
    short_term_collection = initialize_chromadb("short_term")
    ltm_storage = ChromaDBStorage(long_term_collection, openai_api_key)
    stm_storage = ChromaDBStorage(short_term_collection, openai_api_key)

    context = ltm_storage.fetch_relevant(user_input)

    task_define_problem = Task(
        description="""Clarify and define the questions, 
            including identifying the problem type and specific requirements.
            
            Here is the user's problem:

            {ml_problem}
            """.format(ml_problem=user_input),
        agent=Question_Identifier,
        expected_output="A clear and concise definition of the questions.")
    
    task_answer_question= Task(
        description="""Answer and fully clarify the user's question.""",
        agent=Question_Solving,
        expected_output="A clear answer of the full question."
        )
    
    task_summerize_question = Task(
        description="""Summerize the full answer in clear manner.""",
        agent=BramBot,
        expected_output="A clear summerization of the answer."
        )
    
    crew = Crew(
            agents=[Question_Identifier, Question_Solving, BramBot], #, Summarization_Agent],
            tasks=[task_define_problem, task_answer_question, task_summerize_question], #, task_summarize],
            memory=True,
            verbose=True,
            long_term_memory=EnhanceLongTermMemory(
                storage=ltm_storage
            ),
            short_term_memory=EnhanceShortTermMemory(
                storage=stm_storage
            ),
            embedder={
                "provider": "openai",
                "config": {
                    "model": "text-embedding-ada-002",
                    "api_key": openai_api_key
                }
            },
        )

    result = crew.kickoff()
    
    st.session_state.messages.append({"role": "assistant", "content": result.raw})

    with st.chat_message("assistant"):
        st.write(result.raw)