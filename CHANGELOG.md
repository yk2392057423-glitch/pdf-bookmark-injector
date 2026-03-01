# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [1.0.0] - 2026-03-01

### Added
- Web interface for injecting bookmarks into PDF files
- Chinese OCR support via Tesseract (chi_sim)
- Auto-detection of table of contents pages
- Cross-machine offset correction using embedded text priority
- One-click launch script (`启动.bat`)

### Fixed
- Bookmark symbol cleanup (removes special characters from titles)
- Table of contents bookmark handling
- Page offset calculation errors across different machines
- Tesseract `tessdata` path resolution on different environments
- Launch script encoding issue in Windows CMD
