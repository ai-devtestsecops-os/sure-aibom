"""fixture: dataset references"""
import pandas as pd
from datasets import load_dataset

imdb = load_dataset("stanfordnlp/imdb")
df = pd.read_csv("data/train.csv")
local = load_dataset("csv", data_files="data/train.csv")
