# Contributing to Frappe S3 Attachment

Thank you for your interest in contributing to **Frappe S3 Attachment**! This document provides guidelines and best practices for submitting issues, feature requests, and pull requests.

---

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free environment for all contributors. Please be respectful and constructive in all discussions, code reviews, and communications.

---

## How Can I Contribute?

### 1. Reporting Bugs
Before submitting a bug report:
- Search existing [GitHub Issues](https://github.com/LAB-OF-WEB/frappe-attachments-s3/issues) to verify that the bug has not already been reported or resolved.
- Check that your Frappe and Python versions match our supported matrix:
  - **Frappe**: v14, v15, v16
  - **Python**: 3.10+
- Open an issue using the **Bug Report** template with:
  - Clear steps to reproduce the issue.
  - Expected behavior vs. actual behavior.
  - Stack trace or error log snippets (if applicable).
  - Relevant environment details (OS, Frappe version, S3-compatible provider, storage configuration).

### 2. Suggesting Enhancements & Features
We welcome ideas for new features and performance improvements!
- Open an issue using the **Feature Request** template.
- Clearly describe the use case, problem being solved, and proposed implementation design.

### 3. Submitting Pull Requests (PRs)
- **Branch Naming**: Use descriptive branch names:
  - `feat/<feature-name>` (e.g. `feat/restore-progress-bar`)
  - `fix/<issue-description>` (e.g. `fix/empty-content-hash`)
  - `docs/<topic>` (e.g. `docs/iam-least-privilege`)
  - `refactor/<cleanup>`
- **Atomic Commits**: Keep commits concise and meaningful with clear commit messages following Conventional Commits format (`feat: ...`, `fix: ...`, `docs: ...`, `test: ...`).
- **Target Branch**: Submit PRs against `main` (or `develop` where specified).

---

## Development Setup & Workflow

### 1. Local Environment Setup (Frappe Bench)
```bash
# Navigate to your bench directory
cd ~/frappe-bench

# Fetch the repository
bench get-app https://github.com/LAB-OF-WEB/frappe-attachments-s3.git

# Install app onto your development site
bench --site <your-site-name> install-app frappe_s3_attachment
```

### 2. Standalone Development (Without Bench)
You can develop and run tests outside Frappe using standard Python tools:
```bash
# Clone the repository
git clone https://github.com/LAB-OF-WEB/frappe-attachments-s3.git
cd frappe-attachments-s3

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development and linting dependencies
pip install ruff flake8
```

---

## Coding Standards & Style

1. **Python Standards**:
   - Follow **PEP 8** guidelines.
   - Code must pass linting via `ruff` and `flake8`:
     ```bash
     ruff check .
     ```
   - Maximum line length: 120 characters where practical.
   - Use descriptive function and variable names. Avoid abbreviations unless standard in the domain.
   - Ensure backward compatibility across Python 3.10, 3.11, 3.12, and 3.13.

2. **Frappe Best Practices**:
   - Avoid direct database mutations on core doctypes where ORM methods apply; when running bulk direct SQL updates (e.g., migration batching), ensure `frappe.db.commit()` is managed responsibly.
   - Always verify S3 objects before destructive disk deletions (`s3_upload.verify_s3_object_exists`).
   - Use `frappe.publish_realtime` for long-running worker tasks to inform users of live progress.
   - Guard against unauthorized access using Frappe permission checks (`frappe.has_permission`, `check_s3_file_access_permission`).

3. **Documentation**:
   - Update docstrings for all newly introduced public methods and controller hooks.
   - Document any new configuration parameters in `README.md`.

---

## Testing Guidelines

Every bug fix and feature must be accompanied by unit tests:

1. **Running Standalone Tests (CI Mode)**:
   ```bash
   python -m unittest discover -v
   ```
   Our test suite includes self-contained standalone mock definitions for `frappe` and AWS SDKs, ensuring full verification runs in CI environments without requiring live AWS credentials or a running Frappe bench.

2. **Running Inside Frappe Bench**:
   ```bash
   bench --site <your-site-name> run-tests --app frappe_s3_attachment
   ```

3. **Mocking External APIs**:
   - Never call external S3 endpoints during unit tests. Always mock `boto3` client methods (`head_object`, `download_file`, `upload_fileobj`, etc.).
   - Test both success and error/exception paths (e.g. S3 verification failure, permission denied, missing file).

---

## Pull Request Checklist

Before submitting your PR, verify:
- [ ] Tests pass locally: `python -m unittest discover -v`
- [ ] Code passes linting: `ruff check .`
- [ ] New or modified logic is covered by unit tests.
- [ ] PR description details the motivation and changes made.
- [ ] Documentation and `README.md` have been updated if behavior changed.
