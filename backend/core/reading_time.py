"""Shared reading-time estimator for any long-form content in this project
(blog posts, news articles, ...). Strips markdown/HTML markup before counting
so `# Heading`/`**bold**`/`<mark>` etc. don't inflate the word count, weights
fenced code blocks at half prose speed (skimmed, not read), and adds ~10s per
embedded image."""
import math
import re


def estimate_reading_minutes(text):
    text = text or ""
    image_count = len(re.findall(r"!\[[^\]]*\]\([^)]*\)|<img\b", text))
    code_words = sum(len(block.split()) for block in re.findall(r"```.*?```", text, flags=re.DOTALL))
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links/images -> label text
    text = re.sub(r"[#>*_`~|-]+", " ", text)
    prose_words = len(text.split())

    seconds = (prose_words / 200 + code_words / 400) * 60 + image_count * 10
    return max(1, math.ceil(seconds / 60))
