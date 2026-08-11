# coreripper
Developer tools &amp; knowledge hub SaaS platform built with Django


# CoreRipper

A developer-focused tools and knowledge SaaS platform built with Django.

## Overview

CoreRipper brings together developer utilities, a knowledge hub, and AI-assisted features into a single platform. It is designed as a growing suite of tools for developers, with an underlying credit-based billing system to support AI-powered features.

## Tech Stack

- **Backend:** Django, PostgreSQL
- **Frontend:** HTML, CSS, JavaScript
- **Payments:** DPO Pay integration (ZMW/USD)
- **Infrastructure:** Self-hosted on a VPS (Ubuntu)

## Key Features

- **AI Credits System:** A Django-based credit ledger with hold, settle, and release flows, built with concurrency safety in mind for handling simultaneous requests.
- **Knowledge Hub:** A curated resource and reference section for developers, with planned support for webhook ingestion and structured content review.
- **Developer Tools:** A suite of network and developer utilities, including lookup, checking, and diagnostic tools.
- **News Feed Pipeline:** An automated pipeline that detects trending topics, generates draft content, and routes it through an admin review workflow before publishing.
- **Scam and Phishing Detection:** A dedicated module for identifying scam and phishing patterns, with attention to region-specific cases and local data protection considerations.

## Status

CoreRipper is an active, ongoing project. Features are being built and refined incrementally, with a focus on reliability, security, and a clean developer experience.

## Author

Built and maintained by Clive Moono, a BSc Information Technology student and developer based in Zambia.

- GitHub: [github.com/Lilblucher](https://github.com/Lilblucher)
