"""Embedded web server for the OpsPilot interactive modernization interface."""

import http.server
import json
import socketserver
import sys
from pathlib import Path
from typing import Optional

from opspilot.ui.converter_service import ConversionService
from opspilot.audit.auditor import OpsPilotAuditor


class OpsPilotHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """Custom HTTP handler serving the OpsPilot UI and REST API endpoints."""

    def __init__(self, *args, **kwargs):
        self.static_dir = Path(__file__).resolve().parent / "static"
        self.converter = ConversionService()
        self.auditor = OpsPilotAuditor()
        super().__init__(*args, directory=str(self.static_dir), **kwargs)

    def do_GET(self):
        """Handles GET requests for static assets and sample files."""
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            index_path = self.static_dir / "index.html"
            self.wfile.write(index_path.read_bytes())
            return

        elif self.path == "/api/sample":
            # Return PAYROLL.CBL sample legacy file
            sample_file = Path("examples/sample_legacy/PAYROLL.CBL")
            if not sample_file.exists():
                sample_file = Path(__file__).resolve().parent.parent.parent.parent / "examples" / "sample_legacy" / "PAYROLL.CBL"

            content = sample_file.read_text(encoding="utf-8") if sample_file.exists() else ""
            self._send_json_response(200, {
                "filename": "PAYROLL.CBL",
                "content": content
            })
            return

        elif self.path == "/api/sample-sql":
            # Return ORDERS.SQL sample legacy file
            sample_file = Path("examples/sample_legacy/ORDERS.SQL")
            if not sample_file.exists():
                sample_file = Path(__file__).resolve().parent.parent.parent.parent / "examples" / "sample_legacy" / "ORDERS.SQL"

            content = sample_file.read_text(encoding="utf-8") if sample_file.exists() else ""
            self._send_json_response(200, {
                "filename": "ORDERS.SQL",
                "content": content
            })
            return

        elif self.path == "/api/health":
            self._send_json_response(200, {"status": "UP", "service": "OpsPilot Interface"})
            return

        super().do_GET()

    def do_POST(self):
        """Handles modernization conversion and audit requests."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if self.path == "/api/convert":
            try:
                data = json.loads(body.decode("utf-8"))
                filename = data.get("filename", "INPUT.CBL")
                content = data.get("content", "")

                if not content.strip():
                    self._send_json_response(400, {"error": "Content cannot be empty."})
                    return

                result = self.converter.process_cobol(filename=filename, content=content)
                self._send_json_response(200, result)

            except Exception as ex:
                self._send_json_response(500, {"error": f"Conversion processing error: {str(ex)}"})
            return

        elif self.path == "/api/audit":
            try:
                report = self.auditor.run_all_audits()
                self._send_json_response(200, report.to_dict())
            except Exception as ex:
                self._send_json_response(500, {"error": f"Audit execution error: {str(ex)}"})
            return

        self.send_error(404, "Endpoint not found")

    def _send_json_response(self, status_code: int, data: dict):
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response_bytes)

    def log_message(self, format, *args):
        # Clean logging
        sys.stdout.write(f"[{self.log_date_time_string()}] {format % args}\n")


def start_server(host: str = "127.0.0.1", port: int = 8080):
    """Starts the OpsPilot HTTP UI server."""
    # Allow port reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((host, port), OpsPilotHTTPHandler) as httpd:
        url = f"http://{host}:{port}"
        print(f"\n=======================================================")
        print(f"🚀 OpsPilot Modernization Interface running at:")
        print(f"👉 {url}")
        print(f"=======================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down OpsPilot UI server...")
            httpd.server_close()
