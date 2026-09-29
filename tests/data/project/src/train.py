"""fixture: 허브 모델·데이터셋을 이름으로 참조한다"""
from datasets import load_dataset
from transformers import AutoModel

bert = AutoModel.from_pretrained("google-bert/bert-base-uncased")
imdb = load_dataset("stanfordnlp/imdb")
