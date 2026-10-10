#!/usr/bin/env python3
"""Livia's OFFLINE fallback brain.

Dependency-free (pure standard library) intent matcher used ONLY when the AI
providers (Groq, Gemini) are unavailable or rate-limited. It is deliberately
tiny: a bag-of-words / token-overlap scorer over the patterns in intents.json.

Replaces the old scikit-learn + numpy logistic-regression version so the bot
runs in a slim container (and on any python3) with nothing to install.

CLI contract (unchanged, called by whatsapp_bot.js / brain/reply.js):
    python3 train_brain.py "the user message"
Prints a single response line to stdout. On a low-confidence / unknown match it
prints the exact sentinel below so the Node side can route to the last-resort
layer instead of guessing.
"""

import json
import os
import random
import re
import sys
import math
from collections import Counter

LOW_CONFIDENCE_SENTINEL = "__LIVIA_UNSURE__"

INTENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intents.json")

# Words too common to carry intent signal — ignored during scoring.
STOPWORDS = {
    "a", "an", "the", "is", "am", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "and", "or", "but", "if", "so", "do",
    "does", "did", "i", "you", "he", "she", "it", "we", "they", "me", "my",
    "your", "this", "that", "with", "can", "could", "would", "will", "just",
    "please", "pls",
}

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text):
    return [t for t in _TOKEN_RE.findall((text or "").lower())]


def content_tokens(text):
    return [t for t in tokenize(text) if t not in STOPWORDS]


def load_intents():
    with open(INTENTS_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("intents", [])


def build_index(intents):
    """Precompute, per intent: the set of pattern token-sets + document frequency
    so rarer words count for more (a light IDF weighting)."""
    docs = []  # list of (tag, token_counter, raw_tokens_set)
    doc_freq = Counter()
    for intent in intents:
        tag = intent.get("tag", "")
        for pattern in intent.get("patterns", []):
            toks = content_tokens(pattern)
            if not toks:
                toks = tokenize(pattern)  # fall back to all tokens for 1-word stop patterns
            counter = Counter(toks)
            docs.append((tag, counter, set(toks)))
            for t in set(toks):
                doc_freq[t] += 1
    return docs, doc_freq, max(len(docs), 1)


def score(query_tokens, doc_tokens_set, doc_freq, n_docs):
    """Weighted overlap: shared tokens scored by inverse document frequency."""
    if not query_tokens:
        return 0.0
    q = set(query_tokens)
    shared = q & doc_tokens_set
    if not shared:
        return 0.0
    s = 0.0
    for t in shared:
        idf = math.log((n_docs + 1) / (1 + doc_freq.get(t, 0))) + 1.0
        s += idf
    # Normalize by query length so long messages don't inflate the score.
    return s / math.sqrt(len(q))


def predict_response(user_message):
    try:
        intents = load_intents()
    except Exception:
        return LOW_CONFIDENCE_SENTINEL

    responses_by_tag = {
        it.get("tag", ""): it.get("responses", []) for it in intents
    }

    q_tokens = content_tokens(user_message)
    if not q_tokens:
        q_tokens = tokenize(user_message)

    docs, doc_freq, n_docs = build_index(intents)

    best_tag = None
    best_score = 0.0
    for tag, _counter, tok_set in docs:
        sc = score(q_tokens, tok_set, doc_freq, n_docs)
        if sc > best_score:
            best_score = sc
            best_tag = tag

    # Confidence gate. Token-overlap scores for a real hit are typically >= ~1.0;
    # noise sits well below. Keep the bar low enough to be useful, high enough to
    # avoid confidently answering gibberish.
    if best_tag is None or best_score < 1.0:
        return LOW_CONFIDENCE_SENTINEL

    options = responses_by_tag.get(best_tag) or []
    if not options:
        return LOW_CONFIDENCE_SENTINEL
    return random.choice(options)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(predict_response(sys.argv[1]))
    else:
        print(LOW_CONFIDENCE_SENTINEL)
