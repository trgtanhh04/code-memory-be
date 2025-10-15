# python repomix_service.py
import os
import subprocess
import hashlib
import json
from datetime import datetime, timezone
import re
import sys
from typing import Optional, List, Dict, Any

from langchain_google_genai import ChatGoogleGenerativeAI
root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if root not in sys.path:
    sys.path.insert(0, root)
from config.config import OUTPUT_DIR, META_DIR, META_FILE, GOOGLE_API_KEY


class RepoAnalyzerService:
    def __init__(self):
        self.OUTPUT_DIR = OUTPUT_DIR
        self.META_DIR = META_DIR
        self.META_FILE = META_FILE
        self.llm_api_key = GOOGLE_API_KEY

    def get_repo_hash(self, repo_url: str) -> str:
        return hashlib.md5(repo_url.encode('utf-8')).hexdigest()[:8]

    def read_meta(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.META_FILE):
            return []
        try:
            with open(self.META_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            os.makedirs(self.META_DIR, exist_ok=True)
            with open(self.META_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)
            return []
        except Exception:
            return []

    def write_meta(self, meta_list: List[Dict[str, Any]]) -> None:
        os.makedirs(self.META_DIR, exist_ok=True)
        with open(self.META_FILE, 'w', encoding='utf-8') as f:
            json.dump(meta_list, f, indent=2)


    def save_meta(self, repo_url: str, output_file: str) -> None:
        meta_list = self.read_meta()
        data = {
            "repo_url": repo_url,
            "output_file": output_file,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        for i, meta in enumerate(meta_list):
            if meta.get('repo_url') == repo_url:
                meta_list[i] = data
                break
        else:
            meta_list.append(data)
        self.write_meta(meta_list)

    # ------------- Repomix runner -------------
    def run_repomix_remote(self, repo_url: str, outpath: Optional[str] = None, extra_args: Optional[List[str]] = None) -> Optional[str]:

        repo_hash = self.get_repo_hash(repo_url)
        if outpath is None:
            outpath = os.path.join(self.OUTPUT_DIR, f'repomix_output_{repo_hash}.xml')
        os.makedirs(self.OUTPUT_DIR, exist_ok=True)

        if extra_args and isinstance(extra_args, list):
            cmd = ['repomix', *extra_args, '--remote', repo_url, '-o', outpath]
        else:
            cmd = ['repomix', '--remote', repo_url, '-o', outpath]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        if os.path.exists(outpath):
            self.save_meta(repo_url, outpath)
            return outpath

        m = re.search(r"Output to:\s*(.+)", res.stdout)
        if m:
            candidate = m.group(1).strip().strip('"').strip("'")
            if os.path.exists(candidate):
                self.save_meta(repo_url, candidate)
                return candidate
        try:
            import time
            time.sleep(0.3)
            if os.path.exists(outpath):
                self.save_meta(repo_url, outpath)
                return outpath
        except Exception:
            pass

        return None

    # ------------- LLM summarizer -------------
    def llm_summary_repo(self, file_path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(file_path):
            return None

        with open(file_path, 'r', encoding='utf-8') as f:
            text_content = f.read()

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            api_key=self.llm_api_key
        )

        prompt = f"""
            You are an expert software project analyzer. Given the full content of a project, summarize the project and extract the following details:
            1) Project name
            2) Description of the project
            3) Tech stack used (as a concise list of strings; only include key technologies: language, primary framework, main database, AI/embedding tool; ignore minor or generic utilities like dotenv, CORSMiddleware, asyncpg, JSONB, UUID, etc; maximum 8 items)

            Return ONLY a valid JSON object with these keys exactly:
            - "project_name"
            - "description"
            - "tech_stack"

            Do not include Markdown code fences. Here is the full content of the project:
            {text_content}
        """.strip()

        try:
            response = llm.invoke([{
                "role": "user", 
                "content": 
                prompt
            }])
        except Exception:
            return None

        project_info_str = getattr(response, "content", None) or getattr(response, "text", None) or str(response)

        fenced = re.search(r"```json\s*(.*?)\s*```", project_info_str, re.IGNORECASE | re.DOTALL)
        json_str = fenced.group(1) if fenced else project_info_str

        try:
            data = json.loads(json_str)
        except Exception:
            return None
        return data

if __name__ == "__main__":
    service = RepoAnalyzerService()
    output = service.run_repomix_remote("https://github.com/trgtanhh04/Binance-price-API-pipeline.git")
    print("Repomix output file:", output)
    if output:
        summary = service.llm_summary_repo(output)
        print("LLM Summary:", summary)

