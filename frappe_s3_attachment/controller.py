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


@frappe.whitelist()
def file_upload_to_s3(doc, method):
    """
    check and upload files to s3 with resilient atomic ordering.
    """
    s3_upload = S3Operations()
    path = doc.file_url
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

        if doc.is_private:
            method = "frappe_s3_attachment.controller.generate_file"
            file_url = """/api/method/{0}?key={1}&file_name={2}""".format(method, key, doc.file_name)
        else:
            file_url = '{}/{}/{}'.format(
                s3_upload.S3_CLIENT.meta.endpoint_url,
                s3_upload.BUCKET,
                key
            )

        # 1. Update Database FIRST and commit
        frappe.db.sql("""UPDATE `tabFile` SET file_url=%s, folder=%s,
            old_parent=%s, content_hash=%s WHERE name=%s""", (
            file_url, 'Home/Attachments', 'Home/Attachments', key, doc.name))

        doc.file_url = file_url

        if parent_doctype and frappe.get_meta(parent_doctype).get('image_field'):
            frappe.db.set_value(parent_doctype, parent_name, frappe.get_meta(parent_doctype).get('image_field'), file_url)

        frappe.db.commit()

        # 2. Remove local file ONLY after DB commit succeeds
        try:
            os.remove(file_path)
        except (OSError, FileNotFoundError) as e:
            frappe.logger().warning(
                "Could not remove local file {0} after S3 upload: {1}".format(file_path, str(e))
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
    Function to upload all existing files with atomic resilience and head verification.
    """
    file_doc_name = frappe.db.get_value('File', {'name': name})
    if file_doc_name:
        doc = frappe.get_doc('File', name)
        s3_upload = S3Operations()
        path = doc.file_url
        site_path = frappe.utils.get_site_path()
        parent_doctype = doc.attached_to_doctype
        parent_name = doc.attached_to_name
        if not doc.is_private:
            file_path = site_path + '/public' + path
        else:
            file_path = site_path + path

        # File exists?
        if not os.path.exists(file_path):
            return

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
            return

        if doc.is_private:
            method = "frappe_s3_attachment.controller.generate_file"
            file_url = """/api/method/{0}?key={1}&file_name={2}""".format(method, key, doc.file_name)
        else:
            file_url = '{}/{}/{}'.format(
                s3_upload.S3_CLIENT.meta.endpoint_url,
                s3_upload.BUCKET,
                key
            )

        # Update DB first so a crash during removal doesn't leave an orphaned record.
        frappe.db.sql(
            """UPDATE `tabFile` SET file_url=%s, folder=%s,
            old_parent=%s, content_hash=%s WHERE name=%s""",
            (file_url, "Home/Attachments", "Home/Attachments", key, doc.name),
        )
        frappe.db.commit()

        # Remove local file after DB is committed.
        try:
            os.remove(file_path)
        except (OSError, FileNotFoundError):
            frappe.logger().warning(
                "Local file already removed or inaccessible, skipping delete: {0}".format(file_path)
            )


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

    for file in files_list:
        if file.get('file_url'):
            if not s3_file_regex_match(file['file_url']):
                # Skip files that don't physically exist on the server
                if file['is_private']:
                    file_path = site_path + file['file_url']
                else:
                    file_path = site_path + '/public' + file['file_url']
                if not os.path.exists(file_path):
                    frappe.logger().warning(
                        "Skipping missing file: {0} ({1})".format(file['name'], file['file_url'])
                    )
                    skipped_count += 1
                    continue
                try:
                    upload_existing_files_s3(file['name'])
                    migrated_count += 1
                except Exception as e:
                    failed_count += 1
                    frappe.logger().error(
                        "Failed to migrate file {0}: {1}".format(file['name'], str(e))
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
def ping():
    """
    Test function to check if api function work.
    """
    return "pong"
