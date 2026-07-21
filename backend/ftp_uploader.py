import ftplib
import io
import os
from typing import List, Dict, Tuple, Optional

def test_ftp_connection(host: str, port: int = 21, username: str = "", password: str = "", timeout: int = 10) -> Dict:
    """
    Tests connection to a microstock FTP server.
    """
    try:
        if not host:
            return {"success": False, "message": "Host FTP tidak boleh kosong."}

        ftp = ftplib.FTP()
        ftp.connect(host=host, port=port, timeout=timeout)
        ftp.login(user=username, passwd=password)
        ftp.quit()
        return {"success": True, "message": f"Koneksi FTP ke {host} berhasil!"}
    except ftplib.error_perm as e:
        return {"success": False, "message": f"Autentikasi gagal (Username/Password salah): {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"Gagal terhubung ke FTP server {host}:{port}: {str(e)}"}


def upload_files_to_ftp(
    host: str, 
    port: int = 21, 
    username: str = "", 
    password: str = "", 
    remote_dir: str = "/", 
    files_to_upload: List[Tuple[str, bytes]] = [],
    timeout: int = 30
) -> Dict:
    """
    Uploads a list of (filename, file_bytes) tuples to a remote FTP directory.
    """
    if not host or not username:
        return {"success": False, "uploaded_count": 0, "errors": ["Host FTP dan Username wajib diisi."]}

    uploaded_count = 0
    errors = []

    try:
        ftp = ftplib.FTP()
        ftp.connect(host=host, port=port, timeout=timeout)
        ftp.login(user=username, passwd=password)

        if remote_dir and remote_dir != "/":
            try:
                ftp.cwd(remote_dir)
            except Exception:
                try:
                    ftp.mkd(remote_dir)
                    ftp.cwd(remote_dir)
                except Exception as mkd_err:
                    print(f"Directory change warning: {mkd_err}")

        for filename, data_bytes in files_to_upload:
            try:
                bio = io.BytesIO(data_bytes)
                ftp.storlines(f"STOR {filename}", bio) if isinstance(data_bytes, str) else ftp.storbinary(f"STOR {filename}", bio)
                uploaded_count += 1
            except Exception as item_err:
                err_msg = f"Gagal upload {filename}: {str(item_err)}"
                print(err_msg)
                errors.append(err_msg)

        ftp.quit()
        return {
            "success": uploaded_count > 0,
            "uploaded_count": uploaded_count,
            "total": len(files_to_upload),
            "errors": errors
        }

    except Exception as conn_err:
        return {
            "success": False,
            "uploaded_count": 0,
            "total": len(files_to_upload),
            "errors": [f"Gagal koneksi FTP: {str(conn_err)}"]
        }
