---
license: apache-2.0
language:
  - en
  - ko
library_name: transformers
pipeline_tag: text-classification
tags:
  - sentiment
  - text-classification
base_model: acme/acme-base
base_model_relation: finetune
datasets:
  - acme/reviews
  - acmecorpus
model_description: Acme sentiment classifier fine-tuned from acme-base on product reviews.
mask_token: "[MASK]"
widget:
  - text: I love this product
extra_gated_prompt: You agree to use this model only for research.
extra_gated_fields:
  Company: text
  Country: country
co2_eq_emissions:
  emissions: 1250
  source: CodeCarbon
  training_type: fine-tuning
  geographical_location: Seoul, South Korea
  hardware_used: 1 x A100
model-index:
  - name: acme-local
    results:
      - task:
          type: text-classification
          name: Text Classification
        dataset:
          name: Acme Sentiment Eval
          type: acme/sentiment-eval
          split: test
        metrics:
          - type: accuracy
            value: 0.912
            name: Accuracy
          - type: f1
            value: 0.887
---
# acme-local

Acme sentiment classifier for product reviews.
