# Frappe S3 Attachment

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/LAB-OF-WEB/frappe-attachments-s3)
[![Frappe](https://img.shields.io/badge/Frappe-v14%20%7C%20v15%20%7C%20v16-orange.svg)](https://frappeframework.com/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/LAB-OF-WEB/frappe-attachments-s3/actions/workflows/ci.yml/badge.svg)](https://github.com/LAB-OF-WEB/frappe-attachments-s3/actions/workflows/ci.yml)

A robust, enterprise-grade cloud storage integration for **Frappe Framework** and **ERPNext**. Automatically offloads, syncs, streams, and restores public and private file attachments using Amazon S3 or S3-compatible object storage providers (such as Cloudflare R2, MinIO, and DigitalOcean Spaces).

---

## Feature Highlights

- **Background Asynchronous Migration**:
  - Non-blocking, queue-based background migration powered by Frappe background workers (RQ).
  - Live progress tracking directly in the Frappe Desk UI with real-time Socket.IO events (phase status, scanned items, percentage bar, and ETA).
  - Batching architecture built to safely handle hundreds of thousands of files without timeouts or worker memory exhaustion.

- **S3 File Audit & Tracking DocType with Restore to Disk**:
  - Automatically indexes every cloud object in an audit DocType (`S3 File`) mapped to all database records referencing it (`S3 File Link`).
  - **Single & Bulk Restore**: Re-download files from S3 back to the local server disk at any time, automatically updating core `File` records and DocType image fields.

- **Interactive Storage Reclamation Wizard**:
  - Scan and analyze server storage space directly from Frappe Desk.
  - Detects and safely purges:
    - **Duplicate local files** (files already confirmed on S3).
    - **Orphaned disk attachments** (files tied to deleted parent documents).
    - **Unlinked disk files** (files on disk not tracked in the database).

- **Backup-Only Mode**:
  - `do_not_change_file_url`: Mirrors attachments to S3 as an offsite backup while continuing to serve files locally from disk.
  - `disable_s3_upload`: Instantly freeze S3 synchronization without disrupting normal file upload workflows or causing application errors.

- **Atomic S3 Verification**:
  - Uses pre-deletion `head_object` verification before removing any file from local disk, preventing data loss in the event of partial uploads or network hiccups.
  - Deduplication engine: shared files referenced across multiple documents are tracked and uploaded once, updating all linked records atomically.

- **Private File Security & Streaming**:
  - Private files are streamed securely via short-lived presigned URLs after validating user document read permissions (`check_s3_file_access_permission`).
  - Configurable presigned URL expiration times (default: 120 seconds).

- **S3-Compatible Providers**:
  - Full compatibility with custom endpoint URLs (Cloudflare R2, MinIO, DigitalOcean Spaces, Backblaze B2, and Wasabi).

---

## Supported Versions

| Software | Supported Versions | Notes |
| :--- | :--- | :--- |
| **Frappe Framework** | **v14.x, v15.x, v16.x** | Fully compatible with Desk, background RQ workers, and real-time events. |
| **Python** | **3.10, 3.11, 3.12, 3.13** | Continuous integration tested. |
| **Storage Providers** | AWS S3, Cloudflare R2, MinIO, DigitalOcean Spaces | Any S3 API-compliant endpoint. |

---

## Least-Privilege IAM Policy

When provisioning AWS credentials for Frappe S3 Attachment, adhere to the principle of least privilege. Attach the following IAM policy to your IAM user or role (replace `your-bucket-name` with your actual S3 bucket):

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "FrappeS3AttachmentBucketLevelPermissions",
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetBucketLocation"
            ],
            "Resource": "arn:aws:s3:::your-bucket-name"
        },
        {
            "Sid": "FrappeS3AttachmentObjectLevelPermissions",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject"
            ],
            "Resource": "arn:aws:s3:::your-bucket-name/*"
        }
    ]
}
```

> **Note:** If you enable **"Delete From Cloud"** in settings, `s3:DeleteObject` is required. If you do not plan to delete files from S3 when deleted in Frappe, you can omit `s3:DeleteObject`.

---

## Configuration & Setup Guide

### 1. Installation

Download and install the app using Frappe Bench:

```bash
# Navigate to your bench directory
cd ~/frappe-bench

# Fetch the repository
bench get-app https://github.com/LAB-OF-WEB/frappe-attachments-s3.git

# Install onto your target site
bench --site your-site.local install-app frappe_s3_attachment

# Run database migrations
bench --site your-site.local migrate
```

### 2. Configure Credentials

1. Log in to Frappe / ERPNext Desk as **System Manager** or **Administrator**.
2. Search for and open the **S3 File Attachment** single DocType in the Awesomebar.
3. Configure your storage credentials:
   - **Bucket Name**: Your S3 bucket name.
   - **AWS Key**: AWS Access Key ID (or provider access key).
   - **AWS Secret**: AWS Secret Access Key (or provider secret).
   - **S3 Bucket Region Name**: e.g., `us-east-1`, `ap-south-1`, or `auto` for Cloudflare R2.
   - **Endpoint URL** *(Optional)*: Set for custom providers, e.g.:
     - Cloudflare R2: `https://<account-id>.r2.cloudflarestorage.com`
     - MinIO: `http://minio.local:9000`
     - DigitalOcean Spaces: `https://nyc3.digitaloceanspaces.com`
   - **Folder Name** *(Optional)*: Prefix directory path inside the bucket (e.g., `erpnext-attachments`).

### 3. Optional & Advanced Settings

- **Signed URL Expiry Time (Seconds)**: Lifetime for private presigned download URLs (default: `120`).
- **Do Not Delete Local Files**: Retains copies on server disk after successful cloud upload.
- **Do Not Change File URL (Backup-Only Mode)**: Keeps original local file URLs in the database and uses S3 purely as an offsite backup repository.
- **Disable S3 Upload**: Temporarily pauses all S3 uploads without disrupting the site.
- **Delete From Cloud**: Deletes the remote S3 object when a file attachment is deleted from Frappe.

### 4. Migrating Existing Files

To upload existing files from disk to S3:
1. On the **S3 File Attachment** settings page, click the **"Migrate Existing Files"** button.
2. The migration job runs asynchronously via background RQ workers.
3. A live progress modal will display real-time progress via Socket.IO, reporting the current batch, percentage, and completion status.

---

## Storage Reclamation Wizard

To clean up disk storage after migrating to S3:
1. Open **S3 File Attachment** and click **"Reclaim Storage Space"**.
2. The wizard scans:
   - Duplicate local files already verified on S3.
   - Orphaned attachments (files referencing deleted DocTypes/documents).
   - Unlinked local files.
3. Review the scan summary and trigger cleanup for chosen categories safely.

---

## Development & Testing

### Running Tests Standalone (Without Bench)
The test suite can be run in any standard Python environment without live AWS or Frappe bench:

```bash
python -m unittest discover -v
```

### Running Tests in Frappe Bench
```bash
bench --site your-site.local run-tests --app frappe_s3_attachment
```

### Linting
```bash
ruff check .
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

---

## Authors & Credits

- **Current Maintainer**: [LAB-OF-WEB](https://github.com/LAB-OF-WEB)
- **Original Authors & Contributors**: Based on [frappe-attachments-s3](https://github.com/zerodha/frappe-attachments-s3.git) originally created by [Zerodha Technology Pvt. Ltd.](https://zerodha.tech) and contributors:
  - Ramesh Ravi ([@rameshravi](https://github.com/rameshravi))
  - Shridhar Patil ([@shridharpatil](https://github.com/shridharpatil))
  - Sharath C ([@sharathc](https://github.com/sharathc))
  - Fahim Ali Zain ([@faztp12](https://github.com/faztp12))
  - Percival Rapha ([@percival](https://github.com/percival))
  - Abhinav Raut ([@abhinav-raut](https://github.com/abhinav-raut))
  - Karan Sharma ([@karansharma](https://github.com/karansharma))
  - Sivankar Jain ([@sivankar](https://github.com/sivankar))
  - Sakshi-Greycube ([@Sakshi-Greycube](https://github.com/Sakshi-Greycube))

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
