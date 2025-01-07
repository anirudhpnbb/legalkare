import os
import requests
from dotenv import load_dotenv

load_dotenv()


def search_ikanoon(api_token, query, pagenum=0):
    url = "https://api.indiankanoon.org/search/"
    payload = {
        "formInput": query,
        "pagenum": pagenum,
    }
    headers = {
        "Authorization": f"Token {api_token}",
        "Accept": "application/json",
    }
    response = requests.post(url, headers=headers, data=payload, timeout=30)
    response.raise_for_status()  # Raises HTTPError if status != 200
    return response.json()


def fetch_document(api_token, docid):
    url = f"https://api.indiankanoon.org/doc/{docid}/"
    headers = {
        "Authorization": f"Token {api_token}",
        "Accept": "application/json",
    }
    response = requests.post(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def bulk_download(api_token, query="IPC 302", total_count=10, out_dir="ik_downloads"):
    os.makedirs(out_dir, exist_ok=True)
    downloaded = 0
    page = 0

    while downloaded < total_count:
        print(f"Fetching page={page} ...")
        try:
            data = search_ikanoon(api_token, query, pagenum=page)
        except Exception as e:
            print(f"[!] Search error: {e}")
            break

        docs_list = data.get("docs", [])
        if not docs_list:
            print("[!] No more docs, stopping.")
            break

        for doc_info in docs_list:
            if downloaded >= total_count:
                break
            docid = doc_info.get("tid")
            if not docid:
                continue

            print(f"   - Downloading docid={docid} ...")
            try:
                doc_data = fetch_document(api_token, docid)
            except Exception as e:
                print(f"[!] Doc fetch error for docid={docid}: {e}")
                continue

            doc_text_html = doc_data.get("doc", "")
            title = doc_info.get("title", f"doc_{docid}")
            safe_title = "".join([c if c.isalnum() else "_" for c in title])[:50]
            filepath = os.path.join(out_dir, f"{docid}_{safe_title}.txt")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(doc_text_html)

            downloaded += 1

        page += 1

    print(f"Done. Downloaded {downloaded} docs.")

if __name__ == "__main__":
    API_TOKEN = os.getenv("SOURCE_DB_TOKEN")
    print(API_TOKEN)
    bulk_download(API_TOKEN, "civil procedure code section 10", total_count=300)