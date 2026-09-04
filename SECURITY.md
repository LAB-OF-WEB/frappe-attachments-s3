# Security Policy

The maintainers of **Frappe S3 Attachment** take the security and integrity of user data, file attachments, and cloud storage systems very seriously.

---

## Supported Versions

Security updates and critical patches are actively provided for the following versions:

| Frappe Version | App Version | Supported          |
|----------------|-------------|--------------------|
| Frappe v16.x   | 1.x / Latest| :white_check_mark: |
| Frappe v15.x   | 1.x / Latest| :white_check_mark: |
| Frappe v14.x   | 1.x / Latest| :white_check_mark: |
| Frappe < v14   | < 1.0       | :x:                |

---

## Reporting a Vulnerability

If you discover a potential security vulnerability or sensitive data leakage issue within this project, please **do not** open a public issue on GitHub.

Instead, please report the vulnerability privately through one of the following channels:
1. **GitHub Security Advisory**: Navigate to the repository's [Security Advisories](https://github.com/LAB-OF-WEB/frappe-attachments-s3/security/advisories) tab and click **"Report a vulnerability"**.
2. **Email**: Contact the maintainers directly at `security@labofweb.com` or via maintainer profile on GitHub ([@LAB-OF-WEB](https://github.com/LAB-OF-WEB)).

### What to Include in Your Report
To help us evaluate and address the report as quickly as possible, please provide:
- A detailed description of the vulnerability and its potential impact.
- Step-by-step reproduction instructions or a minimal Proof of Concept (PoC).
- Affected DocType, hook, or API endpoint (e.g. `/api/method/frappe_s3_attachment.controller.generate_file`).
- Your operating environment (Frappe framework version, Python version, S3 provider).
- Any proposed remediation or mitigation if available.

---

## Vulnerability Handling & Response Process

1. **Acknowledgment**: We will acknowledge receipt of your vulnerability report within **48 hours**.
2. **Assessment & Confirmation**: We will investigate and confirm the issue within **5 business days**, providing an estimated remediation timeline.
3. **Patch Development & Testing**: A security fix will be prepared and tested against all supported Frappe versions.
4. **Coordinated Disclosure**: Once patched, a new release will be published and credit will be given to the reporter (unless anonymity is requested).

---

## Security Best Practices for Users

- **IAM Least Privilege**: Never grant `s3:*` administrative credentials to the Frappe S3 app. Refer to the least-privilege IAM policy in `README.md`.
- **Private File Protection**: Do not enable guest access on private attachment streaming endpoints.
- **Atomic Verification**: Keep S3 head-object verification active to avoid deleting local files prior to confirmed cloud ingestion.
- **Signed URL Expiration**: Configure sensible expiration times (e.g., 60-300 seconds) in **S3 File Attachment** settings for generated presigned download links.
