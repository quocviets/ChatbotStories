  # Product
<!-- impeccable:product-schema 1 -->

## Platform

Web application with a plain HTML/CSS/JavaScript frontend and a FastAPI backend.

## Users

Authors who develop long-form episodic stories and need assistance with planning,
drafting, reviewing, and maintaining continuity.

## Product Purpose

Help an author turn story intent into reviewable drafts while preserving explicit
author control over generated content and long-form continuity.

## Operating Context

- The main interaction is a chat-style composer in `API/static/index.html`.
- Story generation and analysis run through the FastAPI application in
  `AI_engine/app`.
- The author reviews drafts and controls when content is submitted or accepted.
- Speech-to-text is being designed as an optional input method for the existing
  composer, not as an autonomous voice agent.

## Capabilities and Constraints

- The frontend uses browser-native capabilities where practical.
- The backend supports CPython 3.11 and newer.
- Speech dictation must return editable text and must never submit it automatically.
- The proposed speech model runs locally; audio must not be sent to an external
  speech provider.
- Audio must not be stored in PostgreSQL, Redis, browser persistent storage, or
  application logs.
- New dependencies, caches, concurrency, and model downloads require explicit
  owner approval before implementation.

## Evidence on Hand

- `ai_engine_long_form_story.md` describes the product architecture and MVP-1.
- `API/static/index.html`, `API/static/storyController.js`, and
  `API/static/storyService.js` are the current composer surfaces.
- `AI_engine/app/main.py` and `AI_engine/app/api/v1` contain the backend entry point
  and routes.
- The target development machine has an NVIDIA GeForce RTX 3050 Laptop GPU with
  6 GB VRAM and an AMD Ryzen 5 7000-series CPU.

## Product Principles

- The author remains in control: generated or transcribed text is reviewable before
  submission.
- Prefer the smallest native solution that meets the requirement.
- Treat privacy, validation, cleanup, and accessible feedback as product behavior.
- Base performance decisions on measurements from the target hardware.

## Accessibility & Inclusion

- Dictation controls must be keyboard-operable and have an accessible name.
- Recording, processing, success, and error states must be conveyed without relying
  on color alone.
- Permission denial and unsupported-browser errors must provide a clear recovery
  path.

