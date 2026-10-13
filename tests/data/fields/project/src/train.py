from datasets import load_dataset
from transformers import AutoModel, pipeline

bert = AutoModel.from_pretrained("acme/acme-bert")
chat = pipeline("text-generation", model="acme/acme-chat-GGUF")
private = AutoModel.from_pretrained("acme/acme-private")
reviews = load_dataset("acme/reviews")
EVAL_SET = "https://huggingface.co/datasets/acme/eval-set"
DEMO = "https://huggingface.co/spaces/acme/acme-demo"
