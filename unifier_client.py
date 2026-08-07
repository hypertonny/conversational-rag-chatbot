import json
import time
import requests
from typing import Dict, Any, Optional, Tuple, Union

class UnifierClient:
    """
    Client wrapper for Oracle Primavera Unifier REST APIs v1.
    Handles Bearer Token authentication, JSON payloads, and error formatting.
    """

    DEFAULT_BASE_URL = "https://us2.unifier.oraclecloud.com/consulting/test/ws/rest/service/v1"

    def __init__(self, bearer_token: str, base_url: Optional[str] = None, timeout: int = 30):
        self.bearer_token = bearer_token.strip() if bearer_token else ""
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _get_headers(self, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if custom_headers:
            headers.update(custom_headers)
        return headers

    def test_connection(self) -> Tuple[bool, str, int]:
        """
        Quick check to verify token and base URL reachability.
        """
        if not self.bearer_token:
            return False, "Bearer Token is missing.", 0

        url = f"{self.base_url}/admin/projectshell?Status=Active"
        try:
            start_time = time.time()
            resp = self.session.get(url, headers=self._get_headers(), timeout=self.timeout)
            elapsed_ms = int((time.time() - start_time) * 1000)
            if resp.status_code in (200, 201):
                return True, f"Connection successful! HTTP {resp.status_code} ({elapsed_ms}ms)", resp.status_code
            elif resp.status_code == 401:
                return False, "Unauthorized (HTTP 401): Please verify your Bearer Token.", resp.status_code
            elif resp.status_code == 403:
                return False, "Forbidden (HTTP 403): Token lacks permission for this endpoint.", resp.status_code
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code
        except requests.exceptions.RequestException as e:
            return False, f"Network/Connection error: {str(e)}", 0

    def get_active_projects(self) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float]:
        """
        Fetch active projects list.
        GET /admin/projectshell?Status=Active
        """
        url = f"{self.base_url}/admin/projectshell?Status=Active"
        return self._send_request("GET", url)

    def get_company_bp_list(self) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float]:
        """
        Fetch company-level Business Processes catalog / list.
        GET /admin/bps
        Returns list of available BPs with bp_model_name, bp_name, studio_source.
        """
        url = f"{self.base_url}/admin/bps"
        return self._send_request("GET", url)

    def get_project_bp_list(self, project_number: str) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float]:
        """
        Fetch project/shell level Business Processes catalog / list.
        GET /admin/bps/{project_number}
        """
        proj_clean = project_number.strip()
        url = f"{self.base_url}/admin/bps/{proj_clean}"
        return self._send_request("GET", url)

    def get_company_bp_records(
        self,
        bpname: str,
        filter_condition: str = "",
        lineitem: str = "yes",
        lineitem_file: str = "yes",
        general_comments: str = "yes",
        attach_all_publications: str = "yes",
        custom_payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float]:
        """
        Fetch company-level Business Process records.
        POST /bp/records/
        """
        url = f"{self.base_url}/bp/records/"
        if custom_payload:
            payload = custom_payload
        else:
            payload = {
                "bpname": bpname,
                "lineitem": lineitem,
                "lineitem_file": lineitem_file,
                "general_comments": general_comments,
                "attach_all_publications": attach_all_publications,
            }
            if filter_condition and filter_condition.strip():
                payload["filter_condition"] = filter_condition.strip()

        return self._send_request("POST", url, json_data=payload)

    def get_project_bp_records(
        self,
        project_number: str,
        bpname: str,
        filter_condition: str = "",
        lineitem: str = "yes",
        lineitem_file: str = "yes",
        general_comments: str = "yes",
        attach_all_publications: str = "yes",
        custom_payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float]:
        """
        Fetch project/shell level Business Process records.
        POST /bp/records/{project_number}
        """
        proj_clean = project_number.strip()
        url = f"{self.base_url}/bp/records/{proj_clean}"
        if custom_payload:
            payload = custom_payload
        else:
            payload = {
                "bpname": bpname,
                "lineitem": lineitem,
                "lineitem_file": lineitem_file,
                "general_comments": general_comments,
                "attach_all_publications": attach_all_publications,
            }
            if filter_condition and filter_condition.strip():
                payload["filter_condition"] = filter_condition.strip()

        return self._send_request("POST", url, json_data=payload)

    def get_users(
        self,
        filter_condition: str = "",
        custom_payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float]:
        """
        Fetch user information.
        POST /admin/user/get
        """
        url = f"{self.base_url}/admin/user/get"
        if custom_payload:
            payload = custom_payload
        else:
            payload = {}
            if filter_condition and filter_condition.strip():
                payload["filterCondition"] = filter_condition.strip()

        return self._send_request("POST", url, json_data=payload)

    def download_bp_file(
        self,
        payload: Dict[str, Any]
    ) -> Tuple[bool, Union[bytes, str], int, float, Dict[str, str]]:
        """
        Download binary file attached to BP record.
        POST /bp/record/file
        """
        url = f"{self.base_url}/bp/record/file"
        headers = self._get_headers()
        # For file download response might be binary
        headers["Accept"] = "*/*"
        
        start_time = time.time()
        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=self.timeout)
            elapsed_ms = (time.time() - start_time) * 1000
            
            resp_headers = dict(resp.headers)
            if resp.status_code in (200, 201):
                return True, resp.content, resp.status_code, elapsed_ms, resp_headers
            else:
                try:
                    err_msg = resp.json()
                except Exception:
                    err_msg = resp.text
                return False, err_msg, resp.status_code, elapsed_ms, resp_headers
        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return False, f"Request failed: {str(e)}", 0, elapsed_ms, {}

    def custom_request(
        self,
        method: str,
        endpoint_or_full_url: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        custom_headers: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float, Dict[str, str]]:
        """
        Execute arbitrary HTTP request for testing & exploring APIs.
        """
        if endpoint_or_full_url.startswith("http://") or endpoint_or_full_url.startswith("https://"):
            url = endpoint_or_full_url
        else:
            clean_ep = endpoint_or_full_url if endpoint_or_full_url.startswith("/") else f"/{endpoint_or_full_url}"
            url = f"{self.base_url}{clean_ep}"

        headers = self._get_headers(custom_headers)
        method_upper = method.upper()

        start_time = time.time()
        try:
            resp = self.session.request(
                method=method_upper,
                url=url,
                headers=headers,
                json=json_data if json_data else None,
                params=params if params else None,
                timeout=self.timeout
            )
            elapsed_ms = (time.time() - start_time) * 1000
            resp_headers = dict(resp.headers)

            try:
                data = resp.json()
            except Exception:
                data = resp.text

            is_success = resp.status_code in (200, 201, 202, 204)
            return is_success, data, resp.status_code, elapsed_ms, resp_headers

        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return False, f"Request Exception: {str(e)}", 0, elapsed_ms, {}

    def _send_request(
        self,
        method: str,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Union[Dict[str, Any], list, str], int, float]:
        headers = self._get_headers()
        start_time = time.time()
        try:
            resp = self.session.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                params=params,
                timeout=self.timeout
            )
            elapsed_ms = (time.time() - start_time) * 1000

            try:
                data = resp.json()
            except Exception:
                data = resp.text

            is_success = resp.status_code in (200, 201)
            return is_success, data, resp.status_code, elapsed_ms

        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return False, f"Network Error: {str(e)}", 0, elapsed_ms
