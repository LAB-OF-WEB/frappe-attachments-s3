from __future__ import unicode_literals

import datetime
import os
import random
import re
import string

import boto3

from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

import frappe


import magic


class S3Operations(object):

    def __init__(self):
        """
        Function to initialise the aws settings from frappe S3 File attachment
        doctype.
        """
        self.s3_settings_doc = frappe.get_doc(
            'S3 File Attachment',
            'S3 File Attachment',
        )
        if (
            self.s3_settings_doc.aws_key and
            self.s3_settings_doc.aws_secret
        ):
            self.S3_CLIENT = boto3.client(
                's3',
                aws_access_key_id=self.s3_settings_doc.aws_key,
                aws_secret_access_key=self.s3_settings_doc.aws_secret,
                region_name=self.s3_settings_doc.region_name,
                config=Config(signature_version='s3v4')
            )
        else:
            self.S3_CLIENT = boto3.client(
                's3',
                region_name=self.s3_settings_doc.region_name,
                config=Config(signature_version='s3v4')
            )
        self.BUCKET = self.s3_settings_doc.bucket_name
        self.folder_name = self.s3_settings_doc.folder_name
        self.do_not_delete_local_files = getattr(
            self.s3_settings_doc, 'do_not_delete_local_files', 0
        )

    def strip_special_chars(self, file_name):
        """
        Strips file charachters which doesnt match the regex.
        """
        regex = re.compile('[^0-9a-zA-Z._-]')
        file_name = regex.sub('', file_name)
        return file_name

    def key_generator(self, file_name, parent_doctype, parent_name):
        """
        Generate keys for s3 objects uploaded with file name attached.
        """
        hook_cmd = frappe.get_hooks().get("s3_key_generator")
        if hook_cmd:
            try:
                k = frappe.get_attr(hook_cmd[0])(
                    file_name=file_name,
                    parent_doctype=parent_doctype,
                    parent_name=parent_name
                )
                if k:
                    return k.rstrip('/').lstrip('/')
            except:
                pass

        file_name = file_name.replace(' ', '_')
        file_name = self.strip_special_chars(file_name)
        key = ''.join(
            random.choice(
                string.ascii_uppercase + string.digits) for _ in range(8)
        )

        today = datetime.datetime.now()
        year = today.strftime("%Y")
        month = today.strftime("%m")
        day = today.strftime("%d")

        doc_path = None

        # Guard against None values to avoid TypeError during concatenation
        parent_doctype = parent_doctype or "unknown"
        parent_name = parent_name or "unknown"

        if not doc_path:
            if self.folder_name:
                final_key = self.folder_name + "/" + year + "/" + month + \
                    "/" + day + "/" + parent_doctype + "/" + key + "_" + \
                    file_name
            else:
                final_key = year + "/" + month + "/" + day + "/" + \
                    parent_doctype + "/" + key + "_" + file_name
            return final_key
        else:
            final_key = doc_path + '/' + key + "_" + file_name
            return final_key

    def verify_s3_object_exists(self, key):
        """
        Verify that the object actually exists in S3 (head_object check).
        """
        try:
            self.S3_CLIENT.head_object(Bucket=self.BUCKET, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            frappe.logger().error(
                "S3 head_object verification failed for key {0}: {1}".format(key, error_code)
            )
            return False
        except Exception as e:
            frappe.logger().error(
                "S3 head_object verification error for key {0}: {1}".format(key, str(e))
            )
            return False

    def upload_files_to_s3_with_key(
            self, file_path, file_name, is_private, parent_doctype, parent_name
    ):
        """
        Uploads a new file to S3.
        Strips the file extension to set the content_type in metadata.
        """
        mime_type = magic.from_file(file_path, mime=True)
        key = self.key_generator(file_name, parent_doctype, parent_name)
        content_type = mime_type
        try:
            extra_args = {
                "ContentType": content_type,
                "Metadata": {
                    "ContentType": content_type,
                    "file_name": file_name
                }
            }
            if not is_private:
                extra_args["ACL"] = 'public-read'

            self.S3_CLIENT.upload_file(
                file_path, self.BUCKET, key,
                ExtraArgs=extra_args
            )

        except (ClientError, BotoCoreError) as e:
            frappe.logger().error(
                "S3 Upload failed for file {0} with error: {1}".format(file_name, str(e))
            )
            frappe.throw(frappe._("File Upload to S3 Failed: {0}").format(str(e)))
        except Exception as e:
            frappe.logger().error(
                "Unexpected error uploading file {0} to S3: {1}".format(file_name, str(e))
            )
            frappe.throw(frappe._("File Upload Failed. Please try again."))
        return key

    def delete_from_s3(self, key):
        """ Delete file from s3"""
        if self.s3_settings_doc.delete_file_from_cloud:
            try:
                self.S3_CLIENT.delete_object(
                    Bucket=self.s3_settings_doc.bucket_name,
                    Key=key
                )
            except ClientError:
                frappe.throw(frappe._("Access denied: Could not delete file"))

    def read_file_from_s3(self, key):
        """
        Function to read file from a s3 file.
        """
        return self.S3_CLIENT.get_object(Bucket=self.BUCKET, Key=key)

    def get_url(self, key, file_name=None):
        """
        Return url.

        :param bucket: s3 bucket name
        :param key: s3 object key
        """
        if self.s3_settings_doc.signed_url_expiry_time:
            self.signed_url_expiry_time = self.s3_settings_doc.signed_url_expiry_time # noqa
        else:
            self.signed_url_expiry_time = 120
        params = {
                'Bucket': self.BUCKET,
                'Key': key,

        }
        if file_name:
            params['ResponseContentDisposition'] = 'filename={}'.format(file_name)

        url = self.S3_CLIENT.generate_presigned_url(
            'get_object',
            Params=params,
            ExpiresIn=self.signed_url_expiry_time,
        )

        return url


def update_all_matching_file_records(original_path, is_private, key, s3_upload):
    """
    Find and update all tabFile records matching the exact original file_url and is_private status,
    including updating attached doctypes with image_fields and logging to S3 File.
    """
    matching_files = frappe.get_all(
        'File',
        filters={
            'file_url': original_path,
            'is_private': 1 if is_private else 0
        },
        fields=['name', 'file_name', 'attached_to_doctype', 'attached_to_name', 'is_private', 'content_hash']
    )

    updated_names = []
    links_data = []
    primary_s3_url = ""
    original_hash = None

    for file_info in matching_files:
        name = file_info['name']
        f_name = file_info.get('file_name') or os.path.basename(original_path)
        attached_doctype = file_info.get('attached_to_doctype')
        attached_name = file_info.get('attached_to_name')
        if file_info.get('content_hash') and not original_hash:
            original_hash = file_info.get('content_hash')

        if is_private:
            method = "frappe_s3_attachment.controller.generate_file"
            file_url = """/api/method/{0}?key={1}&file_name={2}""".format(method, key, f_name)
        else:
            file_url = '{}/{}/{}'.format(
                s3_upload.S3_CLIENT.meta.endpoint_url,
                s3_upload.BUCKET,
                key
            )
        if not primary_s3_url:
            primary_s3_url = file_url

        frappe.db.sql(
            """UPDATE `tabFile` SET file_url=%s, folder=%s,
            old_parent=%s, content_hash=%s WHERE name=%s""",
            (file_url, 'Home/Attachments', 'Home/Attachments', key, name)
        )

        image_field_name = None
        if attached_doctype and attached_name:
            try:
                meta = frappe.get_meta(attached_doctype)
                if meta and meta.get('image_field'):
                    image_field_name = meta.get('image_field')
                    frappe.db.set_value(attached_doctype, attached_name, image_field_name, file_url)
            except Exception as e:
                frappe.logger().warning(
                    "Could not update image_field for {0} {1}: {2}".format(attached_doctype, attached_name, str(e))
                )

        links_data.append({
            "file_doc": name,
            "attached_to_doctype": attached_doctype,
            "attached_to_name": attached_name,
            "image_field": image_field_name,
            "original_value": original_path,
            "s3_value": file_url,
            "restored": 0
        })
        updated_names.append(name)

    # Create S3 File tracking entry for full visibility and restoration capability
    try:
        s3_file_doc = frappe.new_doc('S3 File')
        s3_file_doc.file_name = os.path.basename(original_path)
        s3_file_doc.s3_key = key
        s3_file_doc.bucket_name = s3_upload.BUCKET
        s3_file_doc.original_file_url = original_path
        s3_file_doc.s3_url = primary_s3_url
        s3_file_doc.content_hash = original_hash or ""
        s3_file_doc.is_private = 1 if is_private else 0
        s3_file_doc.status = "Active"
        s3_file_doc.migrated_at = frappe.utils.now_datetime()
        for item in links_data:
            s3_file_doc.append("links", item)
        s3_file_doc.insert(ignore_permissions=True)
    except Exception as e:
        frappe.logger().warning(
            "Could not create S3 File tracking record for key {0}: {1}".format(key, str(e))
        )

    frappe.db.commit()
    return updated_names


@frappe.whitelist()
def file_upload_to_s3(doc, method):
    """
    check and upload files to s3 with resilient atomic ordering, updating all duplicate/shared references.
    """
    s3_upload = S3Operations()
    path = doc.file_url
    if not path:
        return

    # If it's already an S3 URL, skip
    if s3_file_regex_match(path):
        return

    site_path = frappe.utils.get_site_path()
    parent_doctype = doc.attached_to_doctype or 'File'
    parent_name = doc.attached_to_name
    ignore_s3_upload_for_doctype = frappe.local.conf.get('ignore_s3_upload_for_doctype') or ['Data Import']
    if parent_doctype not in ignore_s3_upload_for_doctype:
        if not doc.is_private:
            file_path = site_path + '/public' + path
        else:
            file_path = site_path + path

        if not os.path.exists(file_path):
            frappe.logger().warning(
                "Local file not found on disk, skipping S3 upload: {0}".format(file_path)
            )
            return

        key = s3_upload.upload_files_to_s3_with_key(
            file_path, doc.file_name,
            doc.is_private, parent_doctype,
            parent_name
        )

        # Verify file is confirmed on S3 before committing DB or deleting local copy
        if not s3_upload.verify_s3_object_exists(key):
            frappe.throw(frappe._("S3 upload could not be verified on AWS. Local file preserved."))

        # 1. Update ALL tabFile records sharing this exact file_url and commit
        update_all_matching_file_records(path, doc.is_private, key, s3_upload)

        # Sync current in-memory doc
        if doc.is_private:
            method_path = "frappe_s3_attachment.controller.generate_file"
            doc.file_url = """/api/method/{0}?key={1}&file_name={2}""".format(method_path, key, doc.file_name)
        else:
            doc.file_url = '{}/{}/{}'.format(
                s3_upload.S3_CLIENT.meta.endpoint_url,
                s3_upload.BUCKET,
                key
            )

        # 2. Remove local file ONLY after DB commit succeeds (if deletion is enabled)
        if not s3_upload.do_not_delete_local_files:
            try:
                os.remove(file_path)
            except (OSError, FileNotFoundError) as e:
                frappe.logger().warning(
                    "Could not remove local file {0} after S3 upload: {1}".format(file_path, str(e))
                )
        else:
            frappe.logger().info(
                "Local file retained on disk (do_not_delete_local_files enabled): {0}".format(file_path)
            )


@frappe.whitelist()
def generate_file(key=None, file_name=None):
    """
    Function to stream file from s3.
    """
    if key:
        s3_upload = S3Operations()
        signed_url = s3_upload.get_url(key, file_name)
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = signed_url
    else:
        frappe.local.response['body'] = "Key not found."
    return


def upload_existing_files_s3(name):
    """
    Function to upload an existing file and update all File records sharing its file_url.
    Returns list of updated File doc names.
    """
    file_doc_name = frappe.db.get_value('File', {'name': name})
    if not file_doc_name:
        return []

    doc = frappe.get_doc('File', name)
    path = doc.file_url
    if not path or s3_file_regex_match(path):
        return []

    s3_upload = S3Operations()
    site_path = frappe.utils.get_site_path()
    parent_doctype = doc.attached_to_doctype
    parent_name = doc.attached_to_name
    if not doc.is_private:
        file_path = site_path + '/public' + path
    else:
        file_path = site_path + path

    # File exists?
    if not os.path.exists(file_path):
        frappe.logger().warning(
            "Local file not found on disk, skipping S3 upload: {0} ({1})".format(doc.name, file_path)
        )
        return []

    key = s3_upload.upload_files_to_s3_with_key(
        file_path, doc.file_name,
        doc.is_private, parent_doctype,
        parent_name
    )

    # Verify object was written to S3 before database update and local file deletion
    if not s3_upload.verify_s3_object_exists(key):
        frappe.logger().error(
            "S3 verification failed for existing file {0} (key: {1}). Skipping local deletion.".format(doc.name, key)
        )
        return []

    # Update all File records sharing this file_url and commit DB
    updated_names = update_all_matching_file_records(path, doc.is_private, key, s3_upload)

    # Remove local file after DB is committed (if deletion is enabled).
    if not s3_upload.do_not_delete_local_files:
        try:
            os.remove(file_path)
        except (OSError, FileNotFoundError):
            frappe.logger().warning(
                "Local file already removed or inaccessible, skipping delete: {0}".format(file_path)
            )
    else:
        frappe.logger().info(
            "Local file retained on disk (do_not_delete_local_files enabled): {0}".format(file_path)
        )

    return updated_names


def s3_file_regex_match(file_url):
    """
    Match the public file regex match.
    """
    return re.match(
        r'^(https:|/api/method/frappe_s3_attachment.controller.generate_file)',
        file_url
    )


@frappe.whitelist()
def migrate_existing_files():
    """
    Function to enqueue migration of existing files to s3 in background.
    """
    frappe.enqueue(
        "frappe_s3_attachment.controller.process_files_migration",
        queue="long",
        timeout=3600,
        is_async=True,
        user=frappe.session.user
    )
    return {
        "status": "enqueued",
        "message": frappe._("File migration started in background.")
    }


def process_files_migration(user=None):
    """
    Background worker to migrate existing files to s3.
    """
    files_list = frappe.get_all(
        'File',
        fields=['name', 'file_url', 'is_private']
    )
    site_path = frappe.utils.get_site_path()
    migrated_count = 0
    skipped_count = 0
    failed_count = 0
    processed_names = set()

    for file in files_list:
        file_name = file['name']
        if file_name in processed_names:
            continue

        file_url = file.get('file_url')
        if not file_url:
            skipped_count += 1
            processed_names.add(file_name)
            continue

        if s3_file_regex_match(file_url):
            processed_names.add(file_name)
            continue

        # Check if local file exists
        if file.get('is_private'):
            file_path = site_path + file_url
        else:
            file_path = site_path + '/public' + file_url

        if not os.path.exists(file_path):
            frappe.logger().warning(
                "Skipping missing file on disk: {0} ({1})".format(file_name, file_url)
            )
            skipped_count += 1
            processed_names.add(file_name)
            continue

        try:
            updated_names = upload_existing_files_s3(file_name)
            if updated_names:
                migrated_count += len(updated_names)
                processed_names.update(updated_names)
            else:
                skipped_count += 1
                processed_names.add(file_name)
        except Exception as e:
            failed_count += 1
            processed_names.add(file_name)
            frappe.logger().error(
                "Failed to migrate file {0}: {1}".format(file_name, str(e))
            )

    summary_msg = frappe._("S3 Migration completed: {0} migrated, {1} skipped, {2} failed.").format(
        migrated_count, skipped_count, failed_count
    )
    frappe.logger().info(summary_msg)

    frappe.publish_realtime(
        "s3_migration_complete",
        {"message": summary_msg},
        user=user
    )


def delete_from_cloud(doc, method):
    """Delete file from s3"""
    s3 = S3Operations()
    s3.delete_from_s3(doc.content_hash)


@frappe.whitelist()
def restore_all_s3_files():
    """
    Function to enqueue background job to restore all S3 files back to disk without deleting from S3.
    """
    frappe.enqueue(
        "frappe_s3_attachment.controller.process_restore_all_s3_files",
        queue="long",
        timeout=3600,
        is_async=True,
        user=frappe.session.user
    )
    return {
        "status": "enqueued",
        "message": frappe._("File restoration from S3 started in background.")
    }


def process_restore_all_s3_files(user=None):
    """
    Background worker to fetch all files from S3 back to local disk and revert database URLs.
    Does NOT delete files from AWS S3.
    """
    site_path = frappe.utils.get_site_path()
    s3_ops = S3Operations()
    restored_count = 0
    skipped_count = 0
    failed_count = 0
    processed_keys = set()

    # 1. First restore all documented S3 File entries
    try:
        s3_files = frappe.get_all(
            "S3 File",
            filters={"status": ["!=", "Restored"]},
            fields=["name", "s3_key"]
        )
        for s3_f in s3_files:
            try:
                s3_doc = frappe.get_doc("S3 File", s3_f["name"])
                res = s3_doc.restore_to_disk()
                if res.get("status") == "success":
                    restored_count += 1
                    processed_keys.add(s3_doc.s3_key)
                elif res.get("status") == "already_restored":
                    skipped_count += 1
            except Exception as e:
                failed_count += 1
                frappe.logger().error(
                    "Failed restoring S3 File {0}: {1}".format(s3_f["name"], str(e))
                )
    except Exception as e:
        frappe.logger().warning(
            "Could not query S3 File doctype for restore: {0}".format(str(e))
        )

    # 2. Restore any remaining legacy tabFile records with S3 URLs not tracked in S3 File
    try:
        all_files = frappe.get_all(
            "File",
            fields=["name", "file_name", "file_url", "is_private", "content_hash", "attached_to_doctype", "attached_to_name"]
        )
        for f in all_files:
            url = f.get("file_url") or ""
            if not s3_file_regex_match(url):
                continue

            key = f.get("content_hash")
            if not key or "/" not in key:
                if "/api/method/frappe_s3_attachment.controller.generate_file" in url:
                    match = re.search(r"key=([^&]+)", url)
                    if match:
                        key = match.group(1)
                elif s3_ops.BUCKET and s3_ops.BUCKET in url:
                    parts = url.split(s3_ops.BUCKET + "/")
                    if len(parts) > 1:
                        key = parts[1]

            if not key:
                skipped_count += 1
                continue

            if key in processed_keys:
                continue

            # Determine local destination path
            f_name = f.get("file_name") or os.path.basename(key)
            local_url = "/files/" + f_name if not f.get("is_private") else "/private/files/" + f_name
            local_file_path = site_path + ("/public" if not f.get("is_private") else "") + local_url

            try:
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                s3_obj = s3_ops.read_file_from_s3(key)
                with open(local_file_path, "wb") as disk_file:
                    disk_file.write(s3_obj["Body"].read())

                frappe.db.sql(
                    """UPDATE `tabFile` SET file_url=%s WHERE name=%s""",
                    (local_url, f["name"])
                )

                if f.get("attached_to_doctype") and f.get("attached_to_name"):
                    try:
                        meta = frappe.get_meta(f["attached_to_doctype"])
                        if meta and meta.get("image_field"):
                            frappe.db.set_value(
                                f["attached_to_doctype"],
                                f["attached_to_name"],
                                meta.get("image_field"),
                                local_url
                            )
                    except Exception:
                        pass

                frappe.db.commit()
                restored_count += 1
                processed_keys.add(key)
            except Exception as e:
                failed_count += 1
                frappe.logger().error(
                    "Failed restoring file {0} from S3: {1}".format(f["name"], str(e))
                )
    except Exception as e:
        frappe.logger().error("Error querying tabFile for legacy restore: {0}".format(str(e)))

    summary_msg = frappe._("S3 Restore completed: {0} restored, {1} skipped, {2} failed.").format(
        restored_count, skipped_count, failed_count
    )
    frappe.logger().info(summary_msg)

    frappe.publish_realtime(
        "s3_restore_complete",
        {"message": summary_msg},
        user=user
    )


@frappe.whitelist()
def ping():
    """
    Test function to check if api function work.
    """
    return "pong"
