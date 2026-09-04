## Description
Please describe the motivation, summary of changes, and technical design for this pull request.

Fixes #(issue)

---

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Performance optimization / Refactoring
- [ ] CI/CD or build pipeline adjustment

---

## Areas Affected
- [ ] Asynchronous migration / RQ workers / Real-time Socket.IO progress
- [ ] S3 File audit & tracking / Restore to Disk
- [ ] Storage Reclamation Wizard (duplicate, orphaned, unlinked files)
- [ ] Backup-Only Mode (`do_not_change_file_url` / `disable_s3_upload`)
- [ ] Presigned URLs / Streaming download
- [ ] Custom endpoint configuration (MinIO, R2, Spaces, etc.)
- [ ] Unit test suite & mocks

---

## How Has This Been Tested?
Please describe the tests that you ran to verify your changes.

- [ ] Standalone unit tests: `python -m unittest discover -v`
- [ ] Linting: `ruff check .` or `flake8`
- [ ] Bench site test (if applicable): `bench --site <site> run-tests --app frappe_s3_attachment`
- [ ] Manual test on testbench site (public & private attachments)

---

## Checklist
- [ ] My code adheres to the project's coding standards and PEP 8 guidelines.
- [ ] I have added unit tests covering my changes.
- [ ] All existing and new tests pass locally.
- [ ] I have updated relevant documentation / `README.md` if necessary.
- [ ] My PR has a descriptive title and references related issues.
