#! /usr/env python3


import json
import sys
import os
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression

# 1. Load your intents configuration profile
INTENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'intents.json')
with open(INTENTS_FILE, 'r') as file:
    data = json.load(file)

# 2. Extract and organize patterns and labels
training_sentences = []
training_labels = []
intent_responses = {}

for intent in data['intents']:
    tag = intent['tag']
    intent_responses[tag] = intent['responses'][0] # Keep responses handy
    for pattern in intent['patterns']:
        training_sentences.append(pattern.lower())
        training_labels.append(tag)

# 3. Vectorization Engine (Bag of Words Pipeline Matrix)
vectorizer = CountVectorizer()
X_train = vectorizer.fit_transform(training_sentences).toarray()
y_train = training_labels

# 4. Train the Classification Model
# Logistic Regression handles structural text boundaries extremely well
model = LogisticRegression(C=1.0, max_iter=1000)
model.fit(X_train, y_train)

# 5. Live Prediction Interface Execution Gate
def predict_response(user_message):
    user_message = user_message.lower()
    
    # Process text through the same vocabulary matrix mapping
    transformed_input = vectorizer.transform([user_message]).toarray()
    
    # Extract prediction probability distributions
    probabilities = model.predict_proba(transformed_input)[0]
    max_index = np.argmax(probabilities)
    confidence_score = probabilities[max_index]
    
    #confidence_score
    if confidence_score < 0.20:
        return "I'm not completely sure how to help with that request. Please wait for the admin to get online, or visit our website layout details!"
        
    predicted_tag = model.classes_[max_index]
    return intent_responses[predicted_tag]

# Allow execution via runtime arguments from our Node.js gateway
if __name__ == "__main__":
    if len(sys.argv) > 1:
        incoming_query = sys.argv[1]
        print(predict_response(incoming_query))

