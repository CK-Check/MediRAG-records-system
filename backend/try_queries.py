"""try_queries.py - test the agent WITHOUT starting the server.  Run: python try_queries.py"""
from src.agent_pipeline import MediRAGAgent
from src.dp_embeddings import DPHuggingFaceEmbeddings

QUESTIONS = [
    "Calculate the BMI for a patient who weighs 80 kg and is 175 cm tall.",
    "Calculate Maximina's BMI",
    "How did Maximina's weight change from 2010 to 2019?",
    "What was her blood pressure in 2020?",
    "What allergies does Maximina have?",
    "Which medications is Maximina currently taking?",
    "Why was Maximina given vancomycin?",
]


agent = MediRAGAgent(embeddings=DPHuggingFaceEmbeddings())

while True:
    q = input("You: ")
    if(q.lower()=='q'):
        break
    r = agent.ask(q)
    print(f"\nQ: {q}\n[route: {r['intent']}]  sources: {r['sources']}\n{r['answer']}")
    print(f"AI: ", r["answer"])


# Before running the script we need to start the ollama server.
# sudo systemctl stop ollama        -> Closing first server
# OLLAMA_MODELS=/mnt/d/Ollama/OllamaModels OLLAMA_HOST=127.0.0.1:11434 ollama serve 
# ollama run phi3