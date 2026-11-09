# MediRAG Records system

The system is a records retrieval system that is used for the accessing the huge amount of medical records with a help of local AI.

## Description
The system is uses synthetic data from the <a href=https://github.com/synthetichealth/synthea>SYNTHEA</a> tool to generate the synthetic patient data. The data is later processed into source_documents so that the RAG system can access the data effectively. The data is consists of 114 records that acts as a real records database. The whole project is ran on an AI that is being ran locally via OLLAMA phi3 model. 

## Pre-requisites to run the model
- Make sure OLLAMA is running.
- Make sure the phi3 model is installed locally on the server.
- Make sure that the model is running on local server.
- Run the ingest.py file to create the vector database to model to perform RAG.
- You can start the server by running the file api.py
