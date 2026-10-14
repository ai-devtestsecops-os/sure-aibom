import os

import anthropic
from langchain_groq import ChatGroq

client = anthropic.Anthropic()
reply = client.messages.create(model="claude-sonnet-4-5", max_tokens=64, messages=[{"role": "user", "content": "hi"}])
summarizer = ChatGroq(model=os.environ["SUMMARY_MODEL"])
