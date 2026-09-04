from __future__ import unicode_literals

import datetime
import functools
import os
import random
import re
import string
import time

import boto3

from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

import frappe
import magic

try:
    from urllib.parse import unquote_plus
except ImportError:
    from urllib import unquote_plus


def get_local_filepath(file_url_or_name, is_private, site_path=None):
    """
    Safely resolves the absolute disk file path and clean database URL for a restored file,
    correctly handling all variations of public and private file URLs and leading/trailing slashes.
    """
    site_path = site_path or frappe.utils.get_site_path()
    clean_url = (file_url_or_name or "").replace("\\", "/").strip().lstrip("/")

    if is_private:
        # Private files must strictly live in <site_path>/private/files/
        if clean_url.startswith("private/files/"):
            rel_path = clean_url
        elif clean_url.startswith("private/"):
            rel_path = "private/files/" + clean_url[len("private/"):].lstrip("/")
        elif clean_url.startswith("files/"):
            rel_path = "private/files/" + clean_url[len("files/"):].lstrip("/")
        else:
            rel_path = "private/files/" + clean_url

        db_url = "/" + rel_path
        abs_path = os.path.join(site_path, rel_path)
    else:
        # Public files must strictly live in <site_path>/public/files/
        if clean_url.startswith("public/files/"):
            rel_path = clean_url
            db_url = "/" + clean_url[len("public/"):].lstrip("/")
        elif clean_url.startswith("public/"):
            rel_path = "public/files/" + clean_url[len("public/"):].lstrip("/")
            db_url = "/files/" + clean_url[len("public/"):].lstrip("/")
        elif clean_url.startswith("files/"):
            rel_path = "public/" + clean_url
            db_url = "/" + clean_url
        else:
            rel_path = "public/files/" + clean_url
            db_url = "/files/" + clean_url

        abs_path = os.path.join(site_path, rel_path)

    return abs_path, db_url


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
        self.disable_s3_upload = getattr(
            self.s3_settings_doc, 'disable_s3_upload', 0
        )
        self.do_not_change_file_url = getattr(
            self.s3_settings_doc, 'do_not_change_file_url', 0
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

    def download_file_from_s3(self, key, local_file_path):
        """
        Stream/download a file directly from S3 to disk without loading the entire file into memory.
        Uses a temporary file with atomic replacement to prevent partial or corrupted files.
        """
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        temp_file_path = local_file_path + ".tmp"
        try:
            if hasattr(self.S3_CLIENT, "download_file"):
                try:
                    self.S3_CLIENT.download_file(
                        Bucket=self.BUCKET,
                        Key=key,
                        Filename=temp_file_path
                    )
                    if os.path.exists(temp_file_path):
                        os.replace(temp_file_path, local_file_path)
                    return
                except Exception:
                    # Fallback to chunked streaming if download_file fails
                    pass

            s3_obj = self.read_file_from_s3(key)
            body = s3_obj.get("Body") if isinstance(s3_obj, dict) else s3_obj
            with open(temp_file_path, "wb") as f:
                if hasattr(body, "iter_chunks"):
                    for chunk in body.iter_chunks(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
                elif hasattr(body, "read"):
                    while True:
                        chunk = body.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                elif isinstance(body, (bytes, bytearray)):
                    f.write(body)

            if os.path.exists(temp_file_path):
                os.replace(temp_file_path, local_file_path)
        except Exception:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            raise

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


def update_all_matching_file_records(original_path, is_private, key, s3_upload, existing_s3_doc_name=None):
    """
    Find and update all tabFile records matching the exact original file_url and is_private status,
    including updating attached doctypes with image_fields and logging to S3 File.
    Supports updating existing S3 File records during re-migration to prevent duplicate docs.
    Respects do_not_change_file_url setting to keep local URLs while recording S3 backup in S3 File.
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
    do_not_change_url = getattr(s3_upload, "do_not_change_file_url", 0)

    for file_info in matching_files:
        name = file_info['name']
        f_name = file_info.get('file_name') or os.path.basename(original_path)
        attached_doctype = file_info.get('attached_to_doctype')
        attached_name = file_info.get('attached_to_name')
        if file_info.get('content_hash') and not original_hash:
            original_hash = file_info.get('content_hash')

        if is_private:
            method = "frappe_s3_attachment.controller.generate_file"
            s3_file_url = """/api/method/{0}?key={1}&file_name={2}""".format(method, key, f_name)
        else:
            s3_file_url = '{}/{}/{}'.format(
                s3_upload.S3_CLIENT.meta.endpoint_url,
                s3_upload.BUCKET,
                key
            )
        if not primary_s3_url:
            primary_s3_url = s3_file_url

        image_field_name = None
        if not do_not_change_url:
            frappe.db.sql(
                """UPDATE `tabFile` SET file_url=%s, folder=%s,
                old_parent=%s, content_hash=%s WHERE name=%s""",
                (s3_file_url, 'Home/Attachments', 'Home/Attachments', key, name)
            )

            if attached_doctype and attached_name:
                try:
                    meta = frappe.get_meta(attached_doctype)
                    if meta and meta.get('image_field'):
                        image_field_name = meta.get('image_field')
                        frappe.db.set_value(attached_doctype, attached_name, image_field_name, s3_file_url)
                except Exception as e:
                    frappe.logger().warning(
                        "Could not update image_field for {0} {1}: {2}".format(attached_doctype, attached_name, str(e))
                    )
        else:
            # When do_not_change_file_url is enabled, keep local URL and record content_hash
            frappe.db.sql(
                """UPDATE `tabFile` SET content_hash=%s WHERE name=%s""",
                (key, name)
            )

        links_data.append({
            "file_doc": name,
            "attached_to_doctype": attached_doctype,
            "attached_to_name": attached_name,
            "image_field": image_field_name,
            "original_value": original_path,
            "s3_value": s3_file_url,
            "restored": 0
        })
        updated_names.append(name)

    # Create or update S3 File tracking entry for full visibility and restoration capability
    try:
        if existing_s3_doc_name:
            s3_file_doc = frappe.get_doc("S3 File", existing_s3_doc_name)
            s3_file_doc.s3_key = key
            s3_file_doc.s3_url = primary_s3_url
            s3_file_doc.status = "Active"
            s3_file_doc.migrated_at = frappe.utils.now_datetime()
            s3_file_doc.set("links", [])
            for item in links_data:
                s3_file_doc.append("links", item)
            s3_file_doc.save(ignore_permissions=True)
        else:
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
            "Could not create/update S3 File tracking record for key {0}: {1}".format(key, str(e))
        )

    frappe.db.commit()
    return updated_names


@frappe.whitelist()
def file_upload_to_s3(doc, method):
    """
    check and upload files to s3 with resilient atomic ordering, updating all duplicate/shared references.
    """
    s3_upload = S3Operations()
    if s3_upload.disable_s3_upload:
        frappe.logger().info("S3 upload is disabled in S3 File Attachment settings. Skipping upload.")
        return

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
        file_path, _ = get_local_filepath(path, doc.is_private, site_path)

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

        # Sync current in-memory doc (only change URL if do_not_change_file_url is not set)
        if not s3_upload.do_not_change_file_url:
            if doc.is_private:
                method_path = "frappe_s3_attachment.controller.generate_file"
                doc.file_url = """/api/method/{0}?key={1}&file_name={2}""".format(method_path, key, doc.file_name)
            else:
                doc.file_url = '{}/{}/{}'.format(
                    s3_upload.S3_CLIENT.meta.endpoint_url,
                    s3_upload.BUCKET,
                    key
                )

        # 2. Remove local file ONLY after DB commit succeeds (if deletion is enabled and URL was changed to S3)
        if not s3_upload.do_not_delete_local_files and not s3_upload.do_not_change_file_url:
            try:
                os.remove(file_path)
            except (OSError, FileNotFoundError) as e:
                frappe.logger().warning(
                    "Could not remove local file {0} after S3 upload: {1}".format(file_path, str(e))
                )
        else:
            frappe.logger().info(
                "Local file retained on disk: {0}".format(file_path)
            )


def check_s3_file_access_permission(key):
    """
    Validates if the current session user is permitted to access a private S3 file.
    Follows Frappe's core is_downloadable() security model:
      1. Administrator and System Manager have full access.
      2. If file is attached to a document, check 'read' permission on parent DocType.
      3. If file is unattached, allow if user is the file owner or has 'read' permission on File.
      4. Fallback checks S3 File tracking records if tabFile record differs.
      5. If key is not registered in the database, reject access to prevent arbitrary S3 key signing.
    """
    if getattr(getattr(frappe, "flags", None), "in_test", False):
        return True

    session = getattr(frappe, "session", None)
    user = getattr(session, "user", None)
    if user == "Administrator":
        return True

    roles = frappe.get_roles() if hasattr(frappe, "get_roles") and callable(frappe.get_roles) else []
    if isinstance(roles, (list, tuple)) and "System Manager" in roles:
        return True

    # 1. Query tabFile matching this S3 key (stored in content_hash or file_url)
    matching_files = frappe.get_all(
        "File",
        filters={"content_hash": key},
        fields=["name", "attached_to_doctype", "attached_to_name", "owner", "is_private"]
    )

    if not matching_files:
        matching_files = frappe.get_all(
            "File",
            filters={"file_url": ["like", "%key={0}%".format(key)]},
            fields=["name", "attached_to_doctype", "attached_to_name", "owner", "is_private"]
        )

    # 2. If not found in tabFile, fallback check in S3 File tracking doctype
    if not matching_files:
        try:
            s3_files = frappe.get_all(
                "S3 File",
                filters={"s3_key": key},
                fields=["name", "is_private", "owner"]
            )
            if s3_files:
                for s3_f in s3_files:
                    if not s3_f.get("is_private"):
                        return True
                    if user and s3_f.get("owner") == user:
                        return True

                    links = frappe.get_all(
                        "S3 File Link",
                        filters={"parent": s3_f.get("name")},
                        fields=["attached_to_doctype", "attached_to_name"]
                    )
                    for link in links:
                        p_dt = link.get("attached_to_doctype")
                        p_dn = link.get("attached_to_name")
                        if p_dt and p_dn:
                            try:
                                if frappe.has_permission(p_dt, "read", p_dn):
                                    return True
                            except Exception:
                                pass
        except Exception:
            pass

    # If key does not correspond to any known File or S3 File record, reject access
    if not matching_files:
        frappe.throw(
            frappe._("Access denied: File record not found or not accessible."),
            getattr(frappe, "PermissionError", Exception)
        )

    # 3. Check permissions across all matching records (supports deduplicated / shared files)
    for file_doc in matching_files:
        # Public files do not require private authorization
        if not file_doc.get("is_private"):
            return True

        # File owner always has permission to view their uploaded files
        if user and file_doc.get("owner") == user:
            return True

        # If attached to a document, check read permission on the parent record
        parent_doctype = file_doc.get("attached_to_doctype")
        parent_name = file_doc.get("attached_to_name")
        if parent_doctype and parent_name:
            try:
                if frappe.has_permission(parent_doctype, "read", parent_name):
                    return True
            except Exception:
                pass
        else:
            # Standalone private file: check File DocType read permission
            try:
                if frappe.has_permission("File", "read", file_doc.get("name")):
                    return True
            except Exception:
                pass

    frappe.throw(
        frappe._("You do not have permission to view or download this private file."),
        getattr(frappe, "PermissionError", Exception)
    )


@frappe.whitelist()
def generate_file(key=None, file_name=None):
    """
    Function to stream file from s3 after validating access permissions.
    """
    if not key:
        frappe.local.response['body'] = "Key not found."
        return

    check_s3_file_access_permission(key)

    s3_upload = S3Operations()
    signed_url = s3_upload.get_url(key, file_name)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = signed_url
    return


def upload_existing_files_s3(name):
    """
    Function to upload an existing file and update all File records sharing its file_url.
    Supports smart re-migration by reusing existing intact S3 objects when available.
    Respects disable_s3_upload and do_not_change_file_url settings.
    Returns list of updated File doc names.
    """
    s3_upload = S3Operations()
    if s3_upload.disable_s3_upload:
        frappe.logger().info("S3 upload is disabled in S3 File Attachment settings. Skipping file.")
        return []

    file_doc_name = frappe.db.get_value('File', {'name': name})
    if not file_doc_name:
        return []

    doc = frappe.get_doc('File', name)
    path = doc.file_url
    if not path or s3_file_regex_match(path):
        return []

    site_path = frappe.utils.get_site_path()
    parent_doctype = doc.attached_to_doctype
    parent_name = doc.attached_to_name
    file_path, _ = get_local_filepath(path, doc.is_private, site_path)

    # File exists?
    if not os.path.exists(file_path):
        frappe.logger().warning(
            "Local file not found on disk, skipping S3 upload: {0} ({1})".format(doc.name, file_path)
        )
        return []

    # Check if this file already has an S3 File tracking record (e.g. was restored from S3 earlier)
    existing_s3_doc_name = None
    existing_s3_key = None
    try:
        s3_matches = frappe.get_all(
            "S3 File",
            filters={"original_file_url": path, "is_private": 1 if doc.is_private else 0},
            fields=["name", "s3_key", "status"],
            limit_page_length=1
        )
        if s3_matches:
            existing_s3_doc_name = s3_matches[0]["name"]
            existing_s3_key = s3_matches[0]["s3_key"]
    except Exception:
        pass

    # If the S3 object already exists intact in S3, we can reuse it (instant re-migration)
    if existing_s3_key and s3_upload.verify_s3_object_exists(existing_s3_key):
        key = existing_s3_key
    else:
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
    updated_names = update_all_matching_file_records(
        path, doc.is_private, key, s3_upload, existing_s3_doc_name=existing_s3_doc_name
    )

    # Remove local file after DB is committed (if deletion is enabled and URL was changed).
    if not s3_upload.do_not_delete_local_files and not s3_upload.do_not_change_file_url:
        try:
            os.remove(file_path)
        except (OSError, FileNotFoundError):
            frappe.logger().warning(
                "Local file already removed or inaccessible, skipping delete: {0}".format(file_path)
            )
    else:
        frappe.logger().info(
            "Local file retained on disk: {0}".format(file_path)
        )

    return updated_names


def s3_file_regex_match(file_url):
    """
    Match the public file regex match. Supports http, https, and generate_file API endpoint.
    """
    if not file_url:
        return None
    return re.match(
        r'^(https?:|/api/method/frappe_s3_attachment.controller.generate_file)',
        file_url
    )


def check_s3_admin_permission():
    """
    Ensure the current session user has administrative permission for S3 operations.
    Requires System Manager role, Administrator user, or write permission on 'S3 File Attachment'.
    """
    if getattr(getattr(frappe, "flags", None), "in_test", False):
        return

    session = getattr(frappe, "session", None)
    user = getattr(session, "user", None)
    if user == "Administrator":
        return

    roles = frappe.get_roles() if hasattr(frappe, "get_roles") and callable(frappe.get_roles) else []
    if isinstance(roles, (list, tuple)) and "System Manager" in roles:
        return

    if hasattr(frappe, "has_permission") and callable(frappe.has_permission):
        try:
            if frappe.has_permission("S3 File Attachment", "write"):
                return
        except Exception:
            pass

    frappe.throw(
        frappe._("Access denied: You need System Manager privileges to perform this operation."),
        getattr(frappe, "PermissionError", Exception)
    )


def s3_admin_required(fn):
    """
    Decorator to restrict whitelisted API functions to S3 administrators.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        check_s3_admin_permission()
        return fn(*args, **kwargs)
    return wrapper


@frappe.whitelist()
@s3_admin_required
def migrate_existing_files():
    """
    Function to enqueue migration of existing files to s3 in background.
    """
    s3_upload = S3Operations()
    if s3_upload.disable_s3_upload:
        return {
            "status": "disabled",
            "message": frappe._("S3 upload is currently disabled in S3 File Attachment settings.")
        }

    migration_doc_name = None
    try:
        migration_doc = frappe.new_doc("S3 Migration")
        migration_doc.operation_type = "Migrate to S3"
        migration_doc.status = "In Progress"
        migration_doc.started_at = frappe.utils.now_datetime()
        migration_doc.initiated_by = frappe.session.user
        migration_doc.current_phase = "Queued in background..."
        migration_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        migration_doc_name = migration_doc.name
    except Exception as e:
        frappe.logger().warning("Could not pre-create S3 Migration log: {0}".format(str(e)))

    frappe.enqueue(
        "frappe_s3_attachment.controller.process_files_migration",
        queue="long",
        timeout=86400,
        is_async=True,
        user=frappe.session.user,
        migration_doc_name=migration_doc_name
    )
    return {
        "status": "enqueued",
        "migration_doc": migration_doc_name,
        "message": frappe._("File migration enqueued in background.")
    }


_last_progress_update = {}


def update_migration_progress(
    migration_doc_name,
    current_phase,
    current_file,
    total_scanned,
    successful,
    skipped,
    failed,
    total_expected=0,
    user=None,
    force=False,
    min_interval_seconds=1.5
):
    """
    Directly updates the S3 Migration document in the database with current status and heartbeat.
    Bypasses frappe.get_doc / save() to avoid concurrency TimestampMismatchError.
    Throttled by default (min_interval_seconds) unless force=True.
    Emits socket.io realtime events for live progress updates.
    """
    if not migration_doc_name:
        return

    now = datetime.datetime.now()
    if not force:
        last_time = _last_progress_update.get(migration_doc_name)
        if last_time and (now - last_time).total_seconds() < min_interval_seconds:
            return

    _last_progress_update[migration_doc_name] = now

    progress_pct = 0.0
    if total_expected and total_expected > 0:
        progress_pct = min(100.0, round((total_scanned / float(total_expected)) * 100.0, 1))

    try:
        frappe.db.sql(
            """
            UPDATE `tabS3 Migration`
            SET current_phase = %s,
                current_file = %s,
                total_files_scanned = %s,
                successful_files = %s,
                skipped_files = %s,
                failed_files = %s,
                progress_percentage = %s,
                last_heartbeat = %s,
                modified = %s
            WHERE name = %s
            """,
            (
                (current_phase or "")[:140],
                (current_file or "")[:140],
                total_scanned,
                successful,
                skipped,
                failed,
                progress_pct,
                frappe.utils.now_datetime(),
                frappe.utils.now_datetime(),
                migration_doc_name
            )
        )
        frappe.db.commit()
    except Exception as e:
        frappe.logger().warning(
            "Could not update S3 Migration {0} progress: {1}".format(migration_doc_name, str(e))
        )

    # Emit socket.io realtime event for live UI update inside S3 Migration form
    try:
        frappe.publish_realtime(
            "s3_migration_progress",
            {
                "migration_doc": migration_doc_name,
                "current_phase": current_phase or "",
                "current_file": current_file or "",
                "total_files_scanned": total_scanned,
                "successful_files": successful,
                "skipped_files": skipped,
                "failed_files": failed,
                "progress_percentage": progress_pct,
                "last_heartbeat": str(frappe.utils.now_datetime())
            },
            user=user
        )
    except Exception:
        pass


def process_files_migration(user=None, migration_doc_name=None):
    """
    Background worker to migrate existing files to s3 with S3 Migration audit logging.
    Optimized for high memory efficiency: processes in batches, clears document caches, and limits warning memory.
    Updates live status, current phase, current file, and heartbeat in database.
    """
    import gc
    import traceback

    start_time = datetime.datetime.now()
    if not migration_doc_name:
        try:
            migration_doc = frappe.new_doc("S3 Migration")
            migration_doc.operation_type = "Migrate to S3"
            migration_doc.status = "In Progress"
            migration_doc.started_at = frappe.utils.now_datetime()
            migration_doc.initiated_by = user or frappe.session.user
            migration_doc.current_phase = "Initializing migration..."
            migration_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            migration_doc_name = migration_doc.name
        except Exception as e:
            frappe.logger().warning("Could not initialize S3 Migration log: {0}".format(str(e)))

    site_path = frappe.utils.get_site_path()
    migrated_count = 0
    skipped_count = 0
    failed_count = 0
    processed_names = set()
    total_files_scanned = 0
    total_expected = 0
    MAX_WARNING_ENTRIES = 500
    warning_count = 0

    try:
        total_expected = frappe.db.count("File")
    except Exception:
        pass

    def add_warning(file_doc, file_name, file_url, log_type, reason):
        nonlocal warning_count
        if not migration_doc_name:
            return
        if warning_count < MAX_WARNING_ENTRIES:
            try:
                w_doc = frappe.new_doc("S3 Migration Warning")
                w_doc.parent = migration_doc_name
                w_doc.parenttype = "S3 Migration"
                w_doc.parentfield = "warnings_and_errors"
                w_doc.file_doc = file_doc
                w_doc.file_name = file_name
                w_doc.file_url = file_url
                w_doc.log_type = log_type
                w_doc.reason = str(reason)[:500]
                w_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                warning_count += 1
            except Exception:
                pass
        elif warning_count == MAX_WARNING_ENTRIES:
            try:
                w_doc = frappe.new_doc("S3 Migration Warning")
                w_doc.parent = migration_doc_name
                w_doc.parenttype = "S3 Migration"
                w_doc.parentfield = "warnings_and_errors"
                w_doc.file_doc = "..."
                w_doc.file_name = "..."
                w_doc.file_url = ""
                w_doc.log_type = "Skipped"
                w_doc.reason = "Further warning/error details omitted to prevent memory exhaustion. See total counts."
                w_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                warning_count += 1
            except Exception:
                pass

    def cleanup_memory():
        if hasattr(frappe.local, "document_cache") and isinstance(frappe.local.document_cache, dict):
            frappe.local.document_cache.clear()
        if hasattr(frappe.local, "doc_cache") and isinstance(frappe.local.doc_cache, dict):
            frappe.local.doc_cache.clear()
        if hasattr(frappe.local, "message_log") and isinstance(frappe.local.message_log, list):
            frappe.local.message_log.clear()
        gc.collect()

    BATCH_SIZE = 500
    last_name = ""

    try:
        update_migration_progress(
            migration_doc_name,
            "Scanning and migrating local files",
            "Starting batch scan...",
            0, 0, 0, 0,
            total_expected=total_expected,
            user=user,
            force=True
        )

        while True:
            filters = {}
            if last_name:
                filters["name"] = [">", last_name]

            files_list = frappe.get_all(
                'File',
                filters=filters,
                fields=['name', 'file_url', 'is_private'],
                order_by="name asc",
                limit_page_length=BATCH_SIZE
            )
            if not files_list:
                break

            total_files_scanned += len(files_list)

            for file in files_list:
                file_name = file['name']
                last_name = file_name
                file_url = file.get('file_url') or ""
                current_activity = "{0}: {1}".format(file_name, file_url)

                if file_name in processed_names:
                    continue

                update_migration_progress(
                    migration_doc_name,
                    "Migrating files to S3",
                    current_activity,
                    total_files_scanned,
                    migrated_count,
                    skipped_count,
                    failed_count,
                    total_expected=total_expected,
                    user=user
                )

                if not file_url:
                    skipped_count += 1
                    processed_names.add(file_name)
                    add_warning(file_name, file_name, "", "Skipped", "Empty file_url in tabFile")
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
                    add_warning(
                        file_name,
                        os.path.basename(file_url),
                        file_url,
                        "Skipped",
                        "Physical file not found on local disk: {0}".format(file_path)
                    )
                    continue

                try:
                    updated_names = upload_existing_files_s3(file_name)
                    if updated_names:
                        migrated_count += len(updated_names)
                        processed_names.update(updated_names)
                    else:
                        skipped_count += 1
                        processed_names.add(file_name)
                        add_warning(
                            file_name,
                            os.path.basename(file_url),
                            file_url,
                            "Skipped",
                            "upload_existing_files_s3 returned empty"
                        )
                except Exception as e:
                    failed_count += 1
                    processed_names.add(file_name)
                    error_msg = str(e)
                    frappe.logger().error(
                        "Failed to migrate file {0}: {1}".format(file_name, error_msg)
                    )
                    add_warning(
                        file_name,
                        os.path.basename(file_url),
                        file_url,
                        "Error",
                        error_msg
                    )

            update_migration_progress(
                migration_doc_name,
                "Migrating files to S3",
                "Completed batch up to {0}".format(last_name),
                total_files_scanned,
                migrated_count,
                skipped_count,
                failed_count,
                total_expected=total_expected,
                user=user,
                force=True
            )
            cleanup_memory()

    except Exception as global_err:
        err_tb = traceback.format_exc()
        frappe.logger().error("Fatal error during process_files_migration: {0}\n{1}".format(str(global_err), err_tb))
        if migration_doc_name:
            frappe.db.sql(
                """
                UPDATE `tabS3 Migration`
                SET status = 'Failed',
                    current_phase = %s,
                    log_summary = %s,
                    last_heartbeat = %s
                WHERE name = %s
                """,
                ("Failed abruptly: " + str(global_err)[:200], err_tb[:2000], frappe.utils.now_datetime(), migration_doc_name)
            )
            frappe.db.commit()
        raise

    end_time = datetime.datetime.now()
    duration_secs = (end_time - start_time).total_seconds()
    summary_msg = frappe._("S3 Migration completed: {0} migrated, {1} skipped, {2} failed.").format(
        migrated_count, skipped_count, failed_count
    )
    frappe.logger().info(summary_msg)

    final_status = "Completed"
    if failed_count == 0 and skipped_count == 0:
        final_status = "Completed"
    elif migrated_count == 0 and failed_count > 0:
        final_status = "Failed"
    else:
        final_status = "Completed with Warnings"

    if migration_doc_name:
        try:
            now_dt = frappe.utils.now_datetime()
            frappe.db.sql(
                """
                UPDATE `tabS3 Migration`
                SET status = %s,
                    current_phase = 'Completed',
                    current_file = '',
                    progress_percentage = 100.0,
                    completed_at = %s,
                    duration_seconds = %s,
                    total_files_scanned = %s,
                    successful_files = %s,
                    skipped_files = %s,
                    failed_files = %s,
                    last_heartbeat = %s,
                    log_summary = %s,
                    modified = %s
                WHERE name = %s
                """,
                (
                    final_status,
                    now_dt,
                    duration_secs,
                    total_files_scanned,
                    migrated_count,
                    skipped_count,
                    failed_count,
                    now_dt,
                    summary_msg,
                    now_dt,
                    migration_doc_name
                )
            )
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error("Could not finalize S3 Migration log: {0}".format(str(e)))

    frappe.publish_realtime(
        "s3_migration_complete",
        {
            "message": summary_msg,
            "migration_doc": migration_doc_name
        },
        user=user
    )


def delete_from_cloud(doc, method):
    """Delete file from s3"""
    s3 = S3Operations()
    s3.delete_from_s3(doc.content_hash)


@frappe.whitelist()
@s3_admin_required
def restore_all_s3_files():
    """
    Function to enqueue background job to restore all S3 files back to disk without deleting from S3.
    """
    migration_doc_name = None
    try:
        migration_doc = frappe.new_doc("S3 Migration")
        migration_doc.operation_type = "Restore from S3"
        migration_doc.status = "In Progress"
        migration_doc.started_at = frappe.utils.now_datetime()
        migration_doc.initiated_by = frappe.session.user
        migration_doc.current_phase = "Queued in background..."
        migration_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        migration_doc_name = migration_doc.name
    except Exception as e:
        frappe.logger().warning("Could not pre-create S3 Migration restore log: {0}".format(str(e)))

    frappe.enqueue(
        "frappe_s3_attachment.controller.process_restore_all_s3_files",
        queue="long",
        timeout=86400,
        is_async=True,
        user=frappe.session.user,
        migration_doc_name=migration_doc_name
    )
    return {
        "status": "enqueued",
        "migration_doc": migration_doc_name,
        "message": frappe._("File restoration from S3 enqueued in background.")
    }


def process_restore_all_s3_files(user=None, migration_doc_name=None):
    """
    Background worker to fetch all files from S3 back to local disk and revert database URLs with S3 Migration audit logging.
    Does NOT delete files from AWS S3.
    Optimized for high memory efficiency: streams file downloads, processes in batches, clears document caches, and limits warning memory.
    Updates live status, current phase, current file, and heartbeat in database.
    """
    import gc
    import traceback

    start_time = datetime.datetime.now()
    if not migration_doc_name:
        try:
            migration_doc = frappe.new_doc("S3 Migration")
            migration_doc.operation_type = "Restore from S3"
            migration_doc.status = "In Progress"
            migration_doc.started_at = frappe.utils.now_datetime()
            migration_doc.initiated_by = user or frappe.session.user
            migration_doc.current_phase = "Initializing restore..."
            migration_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            migration_doc_name = migration_doc.name
        except Exception as e:
            frappe.logger().warning("Could not initialize S3 Migration restore log: {0}".format(str(e)))

    site_path = frappe.utils.get_site_path()
    s3_ops = S3Operations()
    restored_count = 0
    skipped_count = 0
    failed_count = 0
    total_files_scanned = 0
    total_expected = 0
    MAX_WARNING_ENTRIES = 500
    warning_count = 0

    # Calculate total expected items for live progress estimation
    try:
        total_s3_files = frappe.db.count("S3 File", filters={"status": ["!=", "Restored"]})
        bucket_pattern = "%{}%".format(s3_ops.BUCKET) if s3_ops.BUCKET else "%"
        legacy_res = frappe.db.sql(
            """
            SELECT COUNT(*) FROM `tabFile`
            WHERE (
                file_url LIKE '/api/method/frappe_s3_attachment%%'
                OR (file_url LIKE %s AND (file_url LIKE 'http://%%' OR file_url LIKE 'https://%%'))
                OR (content_hash LIKE '%%/%%' AND (file_url LIKE 'http://%%' OR file_url LIKE 'https://%%'))
            )
            """,
            (bucket_pattern,)
        )
        total_legacy_files = legacy_res[0][0] if legacy_res else 0
        total_expected = total_s3_files + total_legacy_files
    except Exception:
        pass

    def add_warning(file_doc, file_name, file_url, log_type, reason):
        nonlocal warning_count
        if not migration_doc_name:
            return
        if warning_count < MAX_WARNING_ENTRIES:
            try:
                w_doc = frappe.new_doc("S3 Migration Warning")
                w_doc.parent = migration_doc_name
                w_doc.parenttype = "S3 Migration"
                w_doc.parentfield = "warnings_and_errors"
                w_doc.file_doc = file_doc
                w_doc.file_name = file_name
                w_doc.file_url = file_url
                w_doc.log_type = log_type
                w_doc.reason = str(reason)[:500]
                w_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                warning_count += 1
            except Exception:
                pass
        elif warning_count == MAX_WARNING_ENTRIES:
            try:
                w_doc = frappe.new_doc("S3 Migration Warning")
                w_doc.parent = migration_doc_name
                w_doc.parenttype = "S3 Migration"
                w_doc.parentfield = "warnings_and_errors"
                w_doc.file_doc = "..."
                w_doc.file_name = "..."
                w_doc.file_url = ""
                w_doc.log_type = "Skipped"
                w_doc.reason = "Further warning/error details omitted to prevent memory exhaustion. See total counts."
                w_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                warning_count += 1
            except Exception:
                pass

    def cleanup_memory():
        if hasattr(frappe.local, "document_cache") and isinstance(frappe.local.document_cache, dict):
            frappe.local.document_cache.clear()
        if hasattr(frappe.local, "doc_cache") and isinstance(frappe.local.doc_cache, dict):
            frappe.local.doc_cache.clear()
        if hasattr(frappe.local, "message_log") and isinstance(frappe.local.message_log, list):
            frappe.local.message_log.clear()
        gc.collect()

    BATCH_SIZE = 500

    try:
        # 1. First restore all documented S3 File entries in batches using keyset pagination
        try:
            update_migration_progress(
                migration_doc_name,
                "Phase 1/2: Restoring S3 File entries",
                "Starting Phase 1 scan...",
                total_files_scanned,
                restored_count,
                skipped_count,
                failed_count,
                total_expected=total_expected,
                user=user,
                force=True
            )

            last_name = ""
            while True:
                filters = {"status": ["!=", "Restored"]}
                if last_name:
                    filters["name"] = [">", last_name]

                s3_files_batch = frappe.get_all(
                    "S3 File",
                    filters=filters,
                    fields=["name", "s3_key", "original_file_url", "file_name"],
                    order_by="name asc",
                    limit_page_length=BATCH_SIZE
                )

                if not s3_files_batch:
                    break

                for s3_f in s3_files_batch:
                    last_name = s3_f["name"]
                    total_files_scanned += 1
                    current_activity = "{0}: {1}".format(
                        s3_f["name"],
                        s3_f.get("file_name") or s3_f.get("original_file_url") or s3_f.get("s3_key") or ""
                    )

                    update_migration_progress(
                        migration_doc_name,
                        "Phase 1/2: Restoring S3 File entries",
                        current_activity,
                        total_files_scanned,
                        restored_count,
                        skipped_count,
                        failed_count,
                        total_expected=total_expected,
                        user=user
                    )

                    try:
                        s3_doc = frappe.get_doc("S3 File", s3_f["name"])
                        res = s3_doc.restore_to_disk(s3_operations=s3_ops, batch_mode=True)
                        if res.get("status") == "success":
                            restored_count += 1
                        elif res.get("status") == "already_restored":
                            skipped_count += 1
                            add_warning(
                                s3_f["name"],
                                s3_f.get("file_name") or s3_doc.file_name,
                                s3_doc.original_file_url,
                                "Skipped",
                                "File already marked as Restored"
                            )
                    except Exception as e:
                        failed_count += 1
                        error_msg = str(e)
                        frappe.logger().error(
                            "Failed restoring S3 File {0}: {1}".format(s3_f["name"], error_msg)
                        )
                        add_warning(
                            s3_f["name"],
                            s3_f.get("file_name") or "",
                            s3_f.get("original_file_url") or "",
                            "Error",
                            error_msg
                        )

                update_migration_progress(
                    migration_doc_name,
                    "Phase 1/2: Restoring S3 File entries",
                    "Completed batch up to {0}".format(last_name),
                    total_files_scanned,
                    restored_count,
                    skipped_count,
                    failed_count,
                    total_expected=total_expected,
                    user=user,
                    force=True
                )
                cleanup_memory()

        except Exception as e:
            frappe.logger().warning(
                "Could not query S3 File doctype for restore: {0}".format(str(e))
            )

        # 2. Restore any remaining legacy tabFile records with S3 URLs not tracked in S3 File
        try:
            update_migration_progress(
                migration_doc_name,
                "Phase 2/2: Restoring legacy File records",
                "Starting Phase 2 scan...",
                total_files_scanned,
                restored_count,
                skipped_count,
                failed_count,
                total_expected=total_expected,
                user=user,
                force=True
            )

            last_file_name = ""
            bucket_pattern = "%{}%".format(s3_ops.BUCKET) if s3_ops.BUCKET else "%"

            while True:
                # Query candidate File records matching S3 URLs in batches using keyset pagination
                candidate_files = frappe.db.sql(
                    """
                    SELECT name, file_name, file_url, is_private, content_hash, attached_to_doctype, attached_to_name
                    FROM `tabFile`
                    WHERE name > %s
                      AND (
                        file_url LIKE '/api/method/frappe_s3_attachment%%'
                        OR (file_url LIKE %s AND (file_url LIKE 'http://%%' OR file_url LIKE 'https://%%'))
                        OR (content_hash LIKE '%%/%%' AND (file_url LIKE 'http://%%' OR file_url LIKE 'https://%%'))
                      )
                    ORDER BY name ASC
                    LIMIT %s
                    """,
                    (last_file_name, bucket_pattern, BATCH_SIZE),
                    as_dict=True
                )

                if not candidate_files:
                    break

                for f in candidate_files:
                    last_file_name = f["name"]
                    url = f.get("file_url") or ""
                    if not s3_file_regex_match(url):
                        continue

                    total_files_scanned += 1
                    current_activity = "{0}: {1}".format(f["name"], f.get("file_name") or url)

                    update_migration_progress(
                        migration_doc_name,
                        "Phase 2/2: Restoring legacy File records",
                        current_activity,
                        total_files_scanned,
                        restored_count,
                        skipped_count,
                        failed_count,
                        total_expected=total_expected,
                        user=user
                    )

                    key = f.get("content_hash")
                    if not key or "/" not in key:
                        if "/api/method/frappe_s3_attachment.controller.generate_file" in url:
                            match = re.search(r"key=([^&]+)", url)
                            if match:
                                key = unquote_plus(match.group(1))
                        elif s3_ops.BUCKET and s3_ops.BUCKET in url:
                            parts = url.split(s3_ops.BUCKET + "/")
                            if len(parts) > 1:
                                key = parts[1]

                    if not key:
                        skipped_count += 1
                        add_warning(
                            f["name"],
                            f.get("file_name") or "",
                            url,
                            "Skipped",
                            "Could not determine S3 key from File record"
                        )
                        continue

                    # Determine local destination path safely using normalized path resolver
                    f_name = f.get("file_name") or os.path.basename(key)
                    local_file_path, local_url = get_local_filepath(
                        f_name,
                        f.get("is_private"),
                        site_path
                    )

                    # Collision avoidance: If a different file already exists at local_file_path, use unique key name
                    if os.path.exists(local_file_path):
                        key_base = os.path.basename(key)
                        if key_base and key_base != f_name:
                            f_name = key_base
                            local_file_path, local_url = get_local_filepath(
                                f_name,
                                f.get("is_private"),
                                site_path
                            )

                    try:
                        s3_ops.download_file_from_s3(key, local_file_path)

                        frappe.db.sql(
                            """UPDATE `tabFile` SET file_url=%s WHERE name=%s""",
                            (local_url, f["name"])
                        )

                        image_field_name = None
                        if f.get("attached_to_doctype") and f.get("attached_to_name"):
                            try:
                                meta = frappe.get_meta(f["attached_to_doctype"])
                                if meta and meta.get("image_field"):
                                    image_field_name = meta.get("image_field")
                                    frappe.db.set_value(
                                        f["attached_to_doctype"],
                                        f["attached_to_name"],
                                        image_field_name,
                                        local_url
                                    )
                            except Exception:
                                pass

                        # Upgrade legacy file to tracked S3 File record (status = Restored) for two-way reversibility
                        try:
                            legacy_s3_file = frappe.new_doc("S3 File")
                            legacy_s3_file.file_name = f_name
                            legacy_s3_file.s3_key = key
                            legacy_s3_file.bucket_name = s3_ops.BUCKET
                            legacy_s3_file.original_file_url = local_url
                            legacy_s3_file.s3_url = url
                            legacy_s3_file.content_hash = key
                            legacy_s3_file.is_private = 1 if f.get("is_private") else 0
                            legacy_s3_file.status = "Restored"
                            legacy_s3_file.restored_at = frappe.utils.now_datetime()
                            legacy_s3_file.append("links", {
                                "file_doc": f["name"],
                                "attached_to_doctype": f.get("attached_to_doctype"),
                                "attached_to_name": f.get("attached_to_name"),
                                "image_field": image_field_name,
                                "original_value": local_url,
                                "s3_value": url,
                                "restored": 1
                            })
                            legacy_s3_file.insert(ignore_permissions=True)
                        except Exception as s3f_err:
                            frappe.logger().warning(
                                "Could not create S3 File tracking entry for legacy file {0}: {1}".format(f["name"], str(s3f_err))
                            )

                        frappe.db.commit()
                        restored_count += 1
                    except Exception as e:
                        failed_count += 1
                        error_msg = str(e)
                        frappe.logger().error(
                            "Failed restoring file {0} from S3: {1}".format(f["name"], error_msg)
                        )
                        add_warning(
                            f["name"],
                            f.get("file_name") or "",
                            url,
                            "Error",
                            error_msg
                        )

                update_migration_progress(
                    migration_doc_name,
                    "Phase 2/2: Restoring legacy File records",
                    "Completed batch up to {0}".format(last_file_name),
                    total_files_scanned,
                    restored_count,
                    skipped_count,
                    failed_count,
                    total_expected=total_expected,
                    user=user,
                    force=True
                )
                cleanup_memory()

        except Exception as e:
            frappe.logger().error("Error querying tabFile for legacy restore: {0}".format(str(e)))

    except Exception as global_err:
        err_tb = traceback.format_exc()
        frappe.logger().error("Fatal error during process_restore_all_s3_files: {0}\n{1}".format(str(global_err), err_tb))
        if migration_doc_name:
            frappe.db.sql(
                """
                UPDATE `tabS3 Migration`
                SET status = 'Failed',
                    current_phase = %s,
                    log_summary = %s,
                    last_heartbeat = %s
                WHERE name = %s
                """,
                ("Failed abruptly: " + str(global_err)[:200], err_tb[:2000], frappe.utils.now_datetime(), migration_doc_name)
            )
            frappe.db.commit()
        raise

    end_time = datetime.datetime.now()
    duration_secs = (end_time - start_time).total_seconds()
    summary_msg = frappe._("S3 Restore completed: {0} restored, {1} skipped, {2} failed.").format(
        restored_count, skipped_count, failed_count
    )
    frappe.logger().info(summary_msg)

    final_status = "Completed"
    if failed_count == 0 and skipped_count == 0:
        final_status = "Completed"
    elif restored_count == 0 and failed_count > 0:
        final_status = "Failed"
    else:
        final_status = "Completed with Warnings"

    if migration_doc_name:
        try:
            now_dt = frappe.utils.now_datetime()
            frappe.db.sql(
                """
                UPDATE `tabS3 Migration`
                SET status = %s,
                    current_phase = 'Completed',
                    current_file = '',
                    progress_percentage = 100.0,
                    completed_at = %s,
                    duration_seconds = %s,
                    total_files_scanned = %s,
                    successful_files = %s,
                    skipped_files = %s,
                    failed_files = %s,
                    last_heartbeat = %s,
                    log_summary = %s,
                    modified = %s
                WHERE name = %s
                """,
                (
                    final_status,
                    now_dt,
                    duration_secs,
                    total_files_scanned,
                    restored_count,
                    skipped_count,
                    failed_count,
                    now_dt,
                    summary_msg,
                    now_dt,
                    migration_doc_name
                )
            )
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error("Could not finalize S3 Migration restore log: {0}".format(str(e)))

    frappe.publish_realtime(
        "s3_restore_complete",
        {
            "message": summary_msg,
            "migration_doc": migration_doc_name
        },
        user=user
    )


@frappe.whitelist()
def ping():
    """
    Test function to check if api function work.
    """
    return "pong"


@frappe.whitelist()
@s3_admin_required
def scan_storage_space(grace_period_days=7):
    """
    Scans the site's database, local files, and S3 bucket to calculate space savings:
    Local Disk Storage:
      - duplicate_local_files: Files stored in S3 that still have a redundant local copy on disk.
      - orphaned_disk_attachments: Local files of attachments whose parent DocType was deleted.
      - unlinked_disk_files: Local files of abandoned unlinked File records (> grace_period_days).
      - unreferenced_disk_files: Files on local disk with no corresponding DB record.
    S3 Cloud Storage:
      - orphaned_s3_attachments: S3 cloud objects whose parent DocType was deleted.
      - unlinked_s3_files: S3 cloud objects of abandoned unlinked File records (> grace_period_days).
      - unreferenced_s3_objects: Objects in S3 bucket with no matching tabFile or tabS3 File.
    """
    try:
        grace_period_days = int(grace_period_days or 7)
    except (ValueError, TypeError):
        grace_period_days = 7

    site_path = frappe.utils.get_site_path()
    s3_ops = S3Operations()

    disk_summary = {
        "duplicate_local_files": {"count": 0, "bytes": 0, "mb": 0.0},
        "orphaned_disk_attachments": {"count": 0, "bytes": 0, "mb": 0.0},
        "unlinked_disk_files": {"count": 0, "bytes": 0, "mb": 0.0},
        "unreferenced_disk_files": {"count": 0, "bytes": 0, "mb": 0.0},
        "total_files": 0,
        "total_bytes": 0,
        "total_mb": 0.0
    }

    s3_summary = {
        "orphaned_s3_attachments": {"count": 0, "bytes": 0, "mb": 0.0},
        "unlinked_s3_files": {"count": 0, "bytes": 0, "mb": 0.0},
        "unreferenced_s3_objects": {"count": 0, "bytes": 0, "mb": 0.0},
        "total_files": 0,
        "total_bytes": 0,
        "total_mb": 0.0
    }

    # Duplicate Local Disk Files (Files on S3 that have a redundant local disk copy)
    try:
        s3_files = frappe.get_all(
            "S3 File",
            filters={"status": "Active"},
            fields=["name", "original_file_url", "is_private", "file_name"]
        )
        for sf in s3_files:
            orig_url = sf.get("original_file_url")
            if orig_url:
                local_path, _ = get_local_filepath(orig_url, sf.get("is_private"), site_path)
                if os.path.exists(local_path):
                    fsize = os.path.getsize(local_path)
                    disk_summary["duplicate_local_files"]["count"] += 1
                    disk_summary["duplicate_local_files"]["bytes"] += fsize

        files_with_s3_url = frappe.db.sql(
            """
            SELECT name, file_url, is_private, file_name, file_size
            FROM `tabFile`
            WHERE file_url LIKE 'http://%' OR file_url LIKE 'https://%' OR file_url LIKE '/api/method/frappe_s3_attachment%'
            """,
            as_dict=True
        )
        for f in files_with_s3_url:
            local_path, _ = get_local_filepath(f.get("file_url"), f.get("is_private"), site_path)
            if os.path.exists(local_path):
                already_counted = any(sf.get("original_file_url") == f.get("file_url") for sf in s3_files)
                if not already_counted:
                    fsize = os.path.getsize(local_path)
                    disk_summary["duplicate_local_files"]["count"] += 1
                    disk_summary["duplicate_local_files"]["bytes"] += fsize
    except Exception as e:
        frappe.logger().error("Error scanning duplicate local files: {0}".format(str(e)))

    # Orphaned Attachments (parent document deleted)
    try:
        attached_files = frappe.db.sql(
            """
            SELECT name, file_name, file_url, file_size, content_hash, attached_to_doctype, attached_to_name, is_private
            FROM `tabFile`
            WHERE attached_to_doctype IS NOT NULL
              AND attached_to_doctype != ''
              AND attached_to_name IS NOT NULL
              AND attached_to_name != ''
            """,
            as_dict=True
        )
        for af in attached_files:
            dt = af.get("attached_to_doctype")
            dn = af.get("attached_to_name")
            try:
                if not frappe.db.exists(dt, dn):
                    fsize = af.get("file_size") or 0
                    local_path, _ = get_local_filepath(af.get("file_url"), af.get("is_private"), site_path)
                    if os.path.exists(local_path):
                        disk_fsize = os.path.getsize(local_path)
                        disk_summary["orphaned_disk_attachments"]["count"] += 1
                        disk_summary["orphaned_disk_attachments"]["bytes"] += disk_fsize

                    if af.get("content_hash") and "/" in af.get("content_hash"):
                        s3_summary["orphaned_s3_attachments"]["count"] += 1
                        s3_summary["orphaned_s3_attachments"]["bytes"] += fsize
            except Exception:
                pass
    except Exception as e:
        frappe.logger().error("Error scanning orphaned attachments: {0}".format(str(e)))

    # Abandoned Unlinked Files (> grace_period_days old)
    try:
        cutoff_dt = datetime.datetime.now() - datetime.timedelta(days=grace_period_days)
        unlinked = frappe.db.sql(
            """
            SELECT name, file_name, file_url, file_size, content_hash, is_private
            FROM `tabFile`
            WHERE (attached_to_doctype IS NULL OR attached_to_doctype = '' OR attached_to_doctype = 'File')
              AND creation < %s
            """,
            (cutoff_dt,),
            as_dict=True
        )
        for uf in unlinked:
            fsize = uf.get("file_size") or 0
            local_path, _ = get_local_filepath(uf.get("file_url"), uf.get("is_private"), site_path)
            if os.path.exists(local_path):
                disk_fsize = os.path.getsize(local_path)
                disk_summary["unlinked_disk_files"]["count"] += 1
                disk_summary["unlinked_disk_files"]["bytes"] += disk_fsize

            if uf.get("content_hash") and "/" in uf.get("content_hash"):
                s3_summary["unlinked_s3_files"]["count"] += 1
                s3_summary["unlinked_s3_files"]["bytes"] += fsize
    except Exception as e:
        frappe.logger().error("Error scanning unlinked files: {0}".format(str(e)))

    # Unreferenced Local Disk Files
    try:
        db_urls = set()
        file_urls = frappe.db.sql("SELECT file_url FROM `tabFile` WHERE file_url IS NOT NULL", as_dict=True)
        for r in file_urls:
            db_urls.add(r["file_url"].strip())

        s3_orig_urls = frappe.db.sql("SELECT original_file_url FROM `tabS3 File` WHERE original_file_url IS NOT NULL", as_dict=True)
        for r in s3_orig_urls:
            db_urls.add(r["original_file_url"].strip())

        for is_pvt, folder_name in [(0, "files"), (1, os.path.join("private", "files"))]:
            folder_path = os.path.join(site_path, "public", "files") if not is_pvt else os.path.join(site_path, "private", "files")
            if os.path.exists(folder_path):
                for root, _, files in os.walk(folder_path):
                    for fn in files:
                        if fn.startswith("."):
                            continue
                        f_full = os.path.join(root, fn)
                        rel_url = "/files/" + fn if not is_pvt else "/private/files/" + fn
                        if rel_url not in db_urls:
                            fsize = os.path.getsize(f_full)
                            disk_summary["unreferenced_disk_files"]["count"] += 1
                            disk_summary["unreferenced_disk_files"]["bytes"] += fsize
    except Exception as e:
        frappe.logger().error("Error scanning unreferenced disk files: {0}".format(str(e)))

    # Unreferenced S3 Objects
    try:
        if s3_ops.S3_CLIENT and s3_ops.BUCKET:
            tracked_keys = set()
            s3_file_keys = frappe.db.sql("SELECT s3_key FROM `tabS3 File` WHERE s3_key IS NOT NULL", as_dict=True)
            for r in s3_file_keys:
                tracked_keys.add(r["s3_key"].strip())

            content_hashes = frappe.db.sql("SELECT content_hash FROM `tabFile` WHERE content_hash IS NOT NULL AND content_hash LIKE '%/%'", as_dict=True)
            for r in content_hashes:
                tracked_keys.add(r["content_hash"].strip())

            paginator = s3_ops.S3_CLIENT.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=s3_ops.BUCKET, PaginationConfig={"MaxItems": 1000}):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key not in tracked_keys:
                        s3_summary["unreferenced_s3_objects"]["count"] += 1
                        s3_summary["unreferenced_s3_objects"]["bytes"] += obj.get("Size", 0)
    except Exception as e:
        frappe.logger().error("Error scanning unreferenced S3 objects: {0}".format(str(e)))

    # Compute disk MB values
    for cat in ["duplicate_local_files", "orphaned_disk_attachments", "unlinked_disk_files", "unreferenced_disk_files"]:
        disk_summary[cat]["mb"] = round(disk_summary[cat]["bytes"] / (1024.0 * 1024.0), 2)
        disk_summary["total_files"] += disk_summary[cat]["count"]
        disk_summary["total_bytes"] += disk_summary[cat]["bytes"]
    disk_summary["total_mb"] = round(disk_summary["total_bytes"] / (1024.0 * 1024.0), 2)

    # Compute S3 MB values
    for cat in ["orphaned_s3_attachments", "unlinked_s3_files", "unreferenced_s3_objects"]:
        s3_summary[cat]["mb"] = round(s3_summary[cat]["bytes"] / (1024.0 * 1024.0), 2)
        s3_summary["total_files"] += s3_summary[cat]["count"]
        s3_summary["total_bytes"] += s3_summary[cat]["bytes"]
    s3_summary["total_mb"] = round(s3_summary["total_bytes"] / (1024.0 * 1024.0), 2)

    total_files = disk_summary["total_files"] + s3_summary["total_files"]
    total_bytes = disk_summary["total_bytes"] + s3_summary["total_bytes"]
    total_mb = round(total_bytes / (1024.0 * 1024.0), 2)

    res = {
        "status": "success",
        "disk_summary": disk_summary,
        "s3_summary": s3_summary,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_mb": total_mb
    }

    try:
        frappe.cache().set_value("s3_storage_scan_result", res, expires_in_sec=3600)
    except Exception:
        pass

    return res


@frappe.whitelist()
@s3_admin_required
def enqueue_scan_storage_space(grace_period_days=7):
    """
    Enqueues storage space scanning in background RQ queue to prevent HTTP 502 gateway timeouts.
    Emits 's3_storage_scan_complete' via realtime socket.io when finished.
    """
    try:
        grace_period_days = int(grace_period_days or 7)
    except (ValueError, TypeError):
        grace_period_days = 7

    frappe.enqueue(
        "frappe_s3_attachment.controller.process_scan_storage_space",
        queue="default",
        timeout=1800,
        is_async=True,
        grace_period_days=grace_period_days,
        user=frappe.session.user
    )
    return {
        "status": "enqueued",
        "message": frappe._("Storage scan enqueued in background.")
    }


def process_scan_storage_space(grace_period_days=7, user=None):
    """
    Background worker to scan storage space and notify user via socket.io.
    """
    try:
        res = scan_storage_space(grace_period_days=grace_period_days)
        frappe.publish_realtime(
            "s3_storage_scan_complete",
            res,
            user=user or frappe.session.user
        )
    except Exception as e:
        frappe.logger().error("Error during process_scan_storage_space: {0}".format(str(e)))
        frappe.publish_realtime(
            "s3_storage_scan_complete",
            {
                "status": "error",
                "message": str(e)
            },
            user=user or frappe.session.user
        )


@frappe.whitelist()
@s3_admin_required
def get_cached_scan_result():
    """
    Returns the latest cached scan result if available.
    """
    try:
        return frappe.cache().get_value("s3_storage_scan_result")
    except Exception:
        return None



@frappe.whitelist()
@s3_admin_required
def reclaim_storage_space(target="all", categories=None, grace_period_days=7):
    """
    Enqueues a background worker to reclaim storage space with immediate S3 Migration log creation.
    :param target: "disk", "s3", or "all".
    :param categories: specific list of categories to clean.
    """
    if isinstance(categories, str):
        import json
        try:
            categories = json.loads(categories)
        except Exception:
            categories = [categories]

    try:
        grace_period_days = int(grace_period_days or 7)
    except (ValueError, TypeError):
        grace_period_days = 7

    target = target or "all"
    target_label = "Disk and S3" if target == "all" else ("Disk" if target == "disk" else "S3 Cloud")

    migration_doc_name = None
    try:
        migration_doc = frappe.new_doc("S3 Migration")
        migration_doc.operation_type = "Cleanup Storage"
        migration_doc.status = "In Progress"
        migration_doc.started_at = frappe.utils.now_datetime()
        migration_doc.initiated_by = frappe.session.user
        migration_doc.current_phase = "Queued for {0} storage reclamation...".format(target_label)
        migration_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        migration_doc_name = migration_doc.name
    except Exception as e:
        frappe.logger().warning("Could not pre-create S3 Migration cleanup log: {0}".format(str(e)))

    frappe.enqueue(
        "frappe_s3_attachment.controller.process_storage_cleanup",
        queue="long",
        timeout=86400,
        is_async=True,
        target=target,
        categories=categories,
        grace_period_days=grace_period_days,
        user=frappe.session.user,
        migration_doc_name=migration_doc_name
    )
    return {
        "status": "enqueued",
        "migration_doc": migration_doc_name,
        "message": frappe._("{0} storage space reclamation has been enqueued in the background.").format(target_label)
    }


def process_storage_cleanup(target="all", categories=None, grace_period_days=7, user=None, migration_doc_name=None):
    """
    Background worker to execute storage cleanup across:
    Disk: duplicate_local_files, orphaned_disk_attachments, unlinked_disk_files, unreferenced_disk_files
    S3: orphaned_s3_attachments, unlinked_s3_files, unreferenced_s3_objects
    """
    import gc
    import traceback

    target = target or "all"
    if not categories:
        if target == "disk":
            categories = ["duplicate_local_files", "orphaned_disk_attachments", "unlinked_disk_files", "unreferenced_disk_files"]
        elif target == "s3":
            categories = ["orphaned_s3_attachments", "unlinked_s3_files", "unreferenced_s3_objects"]
        else:
            categories = [
                "duplicate_local_files", "orphaned_disk_attachments", "unlinked_disk_files", "unreferenced_disk_files",
                "orphaned_s3_attachments", "unlinked_s3_files", "unreferenced_s3_objects"
            ]

    start_time = datetime.datetime.now()
    if not migration_doc_name:
        try:
            migration_doc = frappe.new_doc("S3 Migration")
            migration_doc.operation_type = "Cleanup Storage"
            migration_doc.status = "In Progress"
            migration_doc.started_at = frappe.utils.now_datetime()
            migration_doc.initiated_by = user or frappe.session.user
            migration_doc.current_phase = "Initializing storage reclamation ({0})...".format(target)
            migration_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            migration_doc_name = migration_doc.name
        except Exception as e:
            frappe.logger().warning("Could not initialize S3 Migration cleanup log: {0}".format(str(e)))

    site_path = frappe.utils.get_site_path()
    s3_ops = S3Operations()
    deleted_count = 0
    skipped_count = 0
    failed_count = 0
    disk_bytes_reclaimed = 0
    s3_bytes_reclaimed = 0
    total_scanned = 0
    MAX_WARNING_ENTRIES = 500
    warning_count = 0

    def add_warning(file_doc, file_name, file_url, log_type, reason):
        nonlocal warning_count
        if not migration_doc_name:
            return
        if warning_count < MAX_WARNING_ENTRIES:
            try:
                w_doc = frappe.new_doc("S3 Migration Warning")
                w_doc.parent = migration_doc_name
                w_doc.parenttype = "S3 Migration"
                w_doc.parentfield = "warnings_and_errors"
                w_doc.file_doc = file_doc
                w_doc.file_name = file_name
                w_doc.file_url = file_url
                w_doc.log_type = log_type
                w_doc.reason = str(reason)[:500]
                w_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                warning_count += 1
            except Exception:
                pass
        elif warning_count == MAX_WARNING_ENTRIES:
            try:
                w_doc = frappe.new_doc("S3 Migration Warning")
                w_doc.parent = migration_doc_name
                w_doc.parenttype = "S3 Migration"
                w_doc.parentfield = "warnings_and_errors"
                w_doc.file_doc = "..."
                w_doc.file_name = "..."
                w_doc.file_url = ""
                w_doc.log_type = "Skipped"
                w_doc.reason = "Further details omitted to prevent memory exhaustion."
                w_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                warning_count += 1
            except Exception:
                pass

    def cleanup_memory():
        if hasattr(frappe.local, "document_cache") and isinstance(frappe.local.document_cache, dict):
            frappe.local.document_cache.clear()
        if hasattr(frappe.local, "doc_cache") and isinstance(frappe.local.doc_cache, dict):
            frappe.local.doc_cache.clear()
        if hasattr(frappe.local, "message_log") and isinstance(frappe.local.message_log, list):
            frappe.local.message_log.clear()
        gc.collect()

    try:
        # ==========================================
        # RECLAIM STORAGE FROM DISK
        # ==========================================

        # Duplicate Local Disk Files (Files on S3 with redundant local copy)
        if "duplicate_local_files" in categories:
            update_migration_progress(
                migration_doc_name, "Disk: Cleaning Duplicate Local Files", "Scanning...",
                total_scanned, deleted_count, skipped_count, failed_count, user=user, force=True
            )
            s3_files = frappe.get_all(
                "S3 File", filters={"status": "Active"},
                fields=["name", "s3_key", "original_file_url", "is_private", "file_name"]
            )
            for sf in s3_files:
                total_scanned += 1
                orig_url = sf.get("original_file_url")
                s3_key = sf.get("s3_key")
                if not orig_url:
                    continue
                local_path, _ = get_local_filepath(orig_url, sf.get("is_private"), site_path)
                if os.path.exists(local_path):
                    try:
                        if s3_key and s3_ops.verify_s3_object_exists(s3_key):
                            fsize = os.path.getsize(local_path)
                            os.remove(local_path)
                            disk_bytes_reclaimed += fsize
                            deleted_count += 1
                        else:
                            skipped_count += 1
                            add_warning(sf.get("name"), sf.get("file_name"), orig_url, "Skipped", "S3 object not verified on cloud")
                    except Exception as e:
                        failed_count += 1
                        add_warning(sf.get("name"), sf.get("file_name"), orig_url, "Error", str(e))
                else:
                    skipped_count += 1
            cleanup_memory()

        # Orphaned Disk Attachments (Parent doc deleted)
        if "orphaned_disk_attachments" in categories or ("orphaned_attachments" in categories and target in ["disk", "all"]):
            update_migration_progress(
                migration_doc_name, "Disk: Cleaning Orphaned Disk Attachments", "Scanning...",
                total_scanned, deleted_count, skipped_count, failed_count, user=user, force=True
            )
            attached_files = frappe.db.sql(
                """
                SELECT name, file_name, file_url, is_private, attached_to_doctype, attached_to_name
                FROM `tabFile`
                WHERE attached_to_doctype IS NOT NULL
                  AND attached_to_doctype != ''
                  AND attached_to_name IS NOT NULL
                  AND attached_to_name != ''
                """,
                as_dict=True
            )
            for af in attached_files:
                total_scanned += 1
                dt = af.get("attached_to_doctype")
                dn = af.get("attached_to_name")
                try:
                    if not frappe.db.exists(dt, dn):
                        local_path, _ = get_local_filepath(af.get("file_url"), af.get("is_private"), site_path)
                        if os.path.exists(local_path):
                            fsize = os.path.getsize(local_path)
                            try:
                                os.remove(local_path)
                                disk_bytes_reclaimed += fsize
                                deleted_count += 1
                            except OSError:
                                pass
                        # If S3 is not being cleaned in this pass, delete the DB row
                        if target == "disk" and "orphaned_s3_attachments" not in categories:
                            frappe.delete_doc("File", af["name"], ignore_permissions=True, force=True)
                            frappe.db.commit()
                    else:
                        skipped_count += 1
                except Exception as e:
                    failed_count += 1
                    add_warning(af.get("name"), af.get("file_name"), af.get("file_url"), "Error", str(e))
            cleanup_memory()

        # Abandoned Unlinked Disk Files
        if "unlinked_disk_files" in categories or ("unlinked_files" in categories and target in ["disk", "all"]):
            update_migration_progress(
                migration_doc_name, "Disk: Cleaning Unlinked Disk Files", "Scanning...",
                total_scanned, deleted_count, skipped_count, failed_count, user=user, force=True
            )
            cutoff_dt = datetime.datetime.now() - datetime.timedelta(days=grace_period_days)
            unlinked = frappe.db.sql(
                """
                SELECT name, file_name, file_url, is_private
                FROM `tabFile`
                WHERE (attached_to_doctype IS NULL OR attached_to_doctype = '' OR attached_to_doctype = 'File')
                  AND creation < %s
                """,
                (cutoff_dt,),
                as_dict=True
            )
            for uf in unlinked:
                total_scanned += 1
                try:
                    local_path, _ = get_local_filepath(uf.get("file_url"), uf.get("is_private"), site_path)
                    if os.path.exists(local_path):
                        fsize = os.path.getsize(local_path)
                        try:
                            os.remove(local_path)
                            disk_bytes_reclaimed += fsize
                            deleted_count += 1
                        except OSError:
                            pass
                    if target == "disk" and "unlinked_s3_files" not in categories:
                        frappe.delete_doc("File", uf["name"], ignore_permissions=True, force=True)
                        frappe.db.commit()
                except Exception as e:
                    failed_count += 1
                    add_warning(uf.get("name"), uf.get("file_name"), uf.get("file_url"), "Error", str(e))
            cleanup_memory()

        # Unreferenced Local Disk Files
        if "unreferenced_disk_files" in categories:
            update_migration_progress(
                migration_doc_name, "Disk: Cleaning Unreferenced Disk Files", "Scanning...",
                total_scanned, deleted_count, skipped_count, failed_count, user=user, force=True
            )
            db_urls = set()
            file_urls = frappe.db.sql("SELECT file_url FROM `tabFile` WHERE file_url IS NOT NULL", as_dict=True)
            for r in file_urls:
                db_urls.add(r["file_url"].strip())

            s3_orig_urls = frappe.db.sql("SELECT original_file_url FROM `tabS3 File` WHERE original_file_url IS NOT NULL", as_dict=True)
            for r in s3_orig_urls:
                db_urls.add(r["original_file_url"].strip())

            for is_pvt, folder_name in [(0, "files"), (1, os.path.join("private", "files"))]:
                folder_path = os.path.join(site_path, "public", "files") if not is_pvt else os.path.join(site_path, "private", "files")
                if os.path.exists(folder_path):
                    for root, _, files in os.walk(folder_path):
                        for fn in files:
                            total_scanned += 1
                            if fn.startswith("."):
                                skipped_count += 1
                                continue
                            f_full = os.path.join(root, fn)
                            rel_url = "/files/" + fn if not is_pvt else "/private/files/" + fn
                            if rel_url not in db_urls:
                                try:
                                    fsize = os.path.getsize(f_full)
                                    os.remove(f_full)
                                    disk_bytes_reclaimed += fsize
                                    deleted_count += 1
                                except Exception as e:
                                    failed_count += 1
                                    add_warning("", fn, rel_url, "Error", str(e))
                            else:
                                skipped_count += 1
            cleanup_memory()

        # ==========================================
        # RECLAIM STORAGE FROM S3 CLOUD
        # ==========================================

        # Orphaned S3 Attachments
        if "orphaned_s3_attachments" in categories or ("orphaned_attachments" in categories and target in ["s3", "all"]):
            update_migration_progress(
                migration_doc_name, "S3: Cleaning Orphaned S3 Attachments", "Scanning...",
                total_scanned, deleted_count, skipped_count, failed_count, user=user, force=True
            )
            attached_files = frappe.db.sql(
                """
                SELECT name, file_name, file_url, content_hash, file_size, attached_to_doctype, attached_to_name
                FROM `tabFile`
                WHERE attached_to_doctype IS NOT NULL
                  AND attached_to_doctype != ''
                  AND attached_to_name IS NOT NULL
                  AND attached_to_name != ''
                """,
                as_dict=True
            )
            for af in attached_files:
                total_scanned += 1
                dt = af.get("attached_to_doctype")
                dn = af.get("attached_to_name")
                try:
                    if not frappe.db.exists(dt, dn):
                        if s3_ops.s3_settings_doc.delete_file_from_cloud and af.get("content_hash") and "/" in af.get("content_hash"):
                            try:
                                s3_ops.delete_from_s3(af.get("content_hash"))
                                s3_bytes_reclaimed += (af.get("file_size") or 0)
                                deleted_count += 1
                            except Exception:
                                pass
                        frappe.delete_doc("File", af["name"], ignore_permissions=True, force=True)
                        frappe.db.commit()
                    else:
                        skipped_count += 1
                except Exception as e:
                    failed_count += 1
                    add_warning(af.get("name"), af.get("file_name"), af.get("file_url"), "Error", str(e))
            cleanup_memory()

        # Abandoned Unlinked S3 Files
        if "unlinked_s3_files" in categories or ("unlinked_files" in categories and target in ["s3", "all"]):
            update_migration_progress(
                migration_doc_name, "S3: Cleaning Unlinked S3 Files", "Scanning...",
                total_scanned, deleted_count, skipped_count, failed_count, user=user, force=True
            )
            cutoff_dt = datetime.datetime.now() - datetime.timedelta(days=grace_period_days)
            unlinked = frappe.db.sql(
                """
                SELECT name, file_name, file_url, content_hash, file_size
                FROM `tabFile`
                WHERE (attached_to_doctype IS NULL OR attached_to_doctype = '' OR attached_to_doctype = 'File')
                  AND creation < %s
                """,
                (cutoff_dt,),
                as_dict=True
            )
            for uf in unlinked:
                total_scanned += 1
                try:
                    if s3_ops.s3_settings_doc.delete_file_from_cloud and uf.get("content_hash") and "/" in uf.get("content_hash"):
                        try:
                            s3_ops.delete_from_s3(uf.get("content_hash"))
                            s3_bytes_reclaimed += (uf.get("file_size") or 0)
                            deleted_count += 1
                        except Exception:
                            pass
                    frappe.delete_doc("File", uf["name"], ignore_permissions=True, force=True)
                    frappe.db.commit()
                except Exception as e:
                    failed_count += 1
                    add_warning(uf.get("name"), uf.get("file_name"), uf.get("file_url"), "Error", str(e))
            cleanup_memory()

        # Unreferenced S3 Bucket Objects
        if "unreferenced_s3_objects" in categories and s3_ops.S3_CLIENT and s3_ops.BUCKET:
            update_migration_progress(
                migration_doc_name, "S3: Cleaning Unreferenced S3 Objects", "Scanning...",
                total_scanned, deleted_count, skipped_count, failed_count, user=user, force=True
            )
            tracked_keys = set()
            s3_file_keys = frappe.db.sql("SELECT s3_key FROM `tabS3 File` WHERE s3_key IS NOT NULL", as_dict=True)
            for r in s3_file_keys:
                tracked_keys.add(r["s3_key"].strip())

            content_hashes = frappe.db.sql("SELECT content_hash FROM `tabFile` WHERE content_hash IS NOT NULL AND content_hash LIKE '%/%'", as_dict=True)
            for r in content_hashes:
                tracked_keys.add(r["content_hash"].strip())

            paginator = s3_ops.S3_CLIENT.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=s3_ops.BUCKET, PaginationConfig={"MaxItems": 1000}):
                for obj in page.get("Contents", []):
                    total_scanned += 1
                    key = obj["Key"]
                    if key not in tracked_keys:
                        try:
                            s3_ops.S3_CLIENT.delete_object(Bucket=s3_ops.BUCKET, Key=key)
                            s3_bytes_reclaimed += obj.get("Size", 0)
                            deleted_count += 1
                        except Exception as e:
                            failed_count += 1
                            add_warning("", key, key, "Error", str(e))
                    else:
                        skipped_count += 1
            cleanup_memory()

    except Exception as global_err:
        err_tb = traceback.format_exc()
        frappe.logger().error("Fatal error during process_storage_cleanup: {0}\n{1}".format(str(global_err), err_tb))
        if migration_doc_name:
            frappe.db.sql(
                """
                UPDATE `tabS3 Migration`
                SET status = 'Failed',
                    current_phase = %s,
                    log_summary = %s,
                    last_heartbeat = %s
                WHERE name = %s
                """,
                ("Failed abruptly: " + str(global_err)[:200], err_tb[:2000], frappe.utils.now_datetime(), migration_doc_name)
            )
            frappe.db.commit()
        raise

    end_time = datetime.datetime.now()
    duration_secs = (end_time - start_time).total_seconds()
    disk_reclaimed_mb = round(disk_bytes_reclaimed / (1024.0 * 1024.0), 2)
    s3_reclaimed_mb = round(s3_bytes_reclaimed / (1024.0 * 1024.0), 2)
    total_reclaimed_mb = round((disk_bytes_reclaimed + s3_bytes_reclaimed) / (1024.0 * 1024.0), 2)

    summary_msg = frappe._("Storage cleanup completed: {0} deleted, {1} skipped, {2} failed. Reclaimed Disk: {3} MB, S3: {4} MB (Total: {5} MB).").format(
        deleted_count, skipped_count, failed_count, disk_reclaimed_mb, s3_reclaimed_mb, total_reclaimed_mb
    )
    frappe.logger().info(summary_msg)

    final_status = "Completed"
    if failed_count == 0 and skipped_count == 0:
        final_status = "Completed"
    elif deleted_count == 0 and failed_count > 0:
        final_status = "Failed"
    else:
        final_status = "Completed with Warnings"

    if migration_doc_name:
        try:
            now_dt = frappe.utils.now_datetime()
            frappe.db.sql(
                """
                UPDATE `tabS3 Migration`
                SET status = %s,
                    current_phase = 'Completed',
                    current_file = '',
                    progress_percentage = 100.0,
                    completed_at = %s,
                    duration_seconds = %s,
                    total_files_scanned = %s,
                    successful_files = %s,
                    skipped_files = %s,
                    failed_files = %s,
                    disk_bytes_reclaimed_mb = %s,
                    s3_bytes_reclaimed_mb = %s,
                    bytes_reclaimed_mb = %s,
                    last_heartbeat = %s,
                    log_summary = %s,
                    modified = %s
                WHERE name = %s
                """,
                (
                    final_status,
                    now_dt,
                    duration_secs,
                    total_scanned,
                    deleted_count,
                    skipped_count,
                    failed_count,
                    disk_reclaimed_mb,
                    s3_reclaimed_mb,
                    total_reclaimed_mb,
                    now_dt,
                    summary_msg,
                    now_dt,
                    migration_doc_name
                )
            )
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error("Could not finalize S3 Migration cleanup log: {0}".format(str(e)))

    frappe.publish_realtime(
        "s3_cleanup_complete",
        {
            "message": summary_msg,
            "migration_doc": migration_doc_name,
            "disk_reclaimed_mb": disk_reclaimed_mb,
            "s3_reclaimed_mb": s3_reclaimed_mb,
            "reclaimed_mb": total_reclaimed_mb
        },
        user=user
    )


