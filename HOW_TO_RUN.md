# How to run docintel

docintel reads documents - PDFs, scans, phone photos, Word, Excel, PowerPoint,
OpenDocument, HTML, e-mails, text, CSV and JSON files - and turns them into structured,
checked data: every value, the label it was printed under, the exact spot on the page it
came from, how the values relate, and a review list of anything it is not sure of. It runs
entirely on your own computer: plain Python and the free Tesseract OCR engine, no AI
model, no internet service.

---

## The quick way

### 1. Install two free programs (once)

| | Windows | macOS | Linux (Ubuntu / Debian) |
|---|---|---|---|
| **Python 3.10 or newer** | <https://www.python.org/downloads/> - in the installer, tick **"Add python.exe to PATH"** | <https://www.python.org/downloads/> or `brew install python` | `sudo apt install python3 python3-venv` |
| **Tesseract OCR** (reads scans and photos) | installer from <https://github.com/UB-Mannheim/tesseract/wiki> (keep the default folder) | `brew install tesseract` | `sudo apt install tesseract-ocr` |

docintel still runs without Tesseract, but scanned pages and photos are then only marked
*Needs OCR* instead of being read.

### 2. Start it

* **Windows:** unzip the folder, then double-click **`run_windows.bat`**.
* **macOS / Linux:** unzip the folder, open a terminal in it and run **`./run_mac_linux.sh`**
  (on macOS you can also right-click the file and open it with Terminal).

The first start takes a minute or two: it creates a private Python environment in the
folder (`.venv`) and installs what docintel needs. Later starts take a few seconds.

Your browser opens **<http://localhost:8000>**. The first time, the app reads the seven
sample forms in `samples/input` so there is something to look at straight away.

To stop it, close the window (or press **Ctrl+C** in it).

### 3. Try it

Click **Upload files** (top right) or drop files on the box at the top left. Ten sample
documents of different kinds are in **`samples/demo/`**:

| file | what it is |
|---|---|
| `01_invoice.pdf` | invoice - number, date, seller and client, items, total |
| `02_receipt_photo.jpg` | phone photo of a cafe receipt, tilted and unevenly lit |
| `03_bank_statement.pdf` | bank statement - account, period, balances, transactions |
| `04_payslip.docx` | payslip as a Word file |
| `05_utility_bill_scan.png` | scanned electricity bill |
| `06_discharge_summary.pdf` | hospital discharge summary |
| `07_prescription_scan.pdf` | scanned prescription (no text layer) |
| `08_purchase_order.xlsx` | purchase order as an Excel sheet |
| `09_payment_reminder.eml` | e-mail about an invoice |
| `10_insurance_claim_form.pdf` | fillable PDF form |

For each document the app shows:

* **Document** tab - the *key facts* (invoice number, total, account number, ...) and the
  whole document in reading order;
* **Entities** and **Relationships** - every value and how they connect;
* **Review** - anything docintel was unsure of, with *Confirm* / *Correct* buttons;
* **Missing**, **Validation** and **Ask** tabs;
* on the right, the page itself: click any value and it is highlighted where it was read.

**Download JSON** and **Markdown** save the result. All names and numbers in the samples
are invented.

---

## The manual way (any system)

```bash
cd DocIntel
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate
pip install -e .
python -m docintel serve            # then open http://localhost:8000
```

Useful commands (with the environment active):

```bash
python -m docintel process samples/demo -o output     # read a folder: one JSON (+ Markdown) per document
python -m docintel evaluate samples/input             # accuracy against the hand-checked answers
pip install -e ".[dev]" && python -m pytest -q        # the test suite (108 tests)
python -m docintel serve --port 8010                  # use another port if 8000 is taken
```

---

## If something goes wrong

| problem | what to do |
|---|---|
| `python` is not recognised (Windows) | reinstall Python and tick **"Add python.exe to PATH"**, or use `py` instead of `python` |
| scans show *Needs OCR* | Tesseract is not installed or not found. On Windows `run_windows.bat` also looks in `C:\Program Files\Tesseract-OCR`; otherwise add the Tesseract folder to `PATH` and start again |
| port 8000 is in use | `python -m docintel serve --port 8010` and open <http://localhost:8010> |
| start over with an empty list | stop the app, delete the `docintel_data` folder, start again |
| `./run_mac_linux.sh: Permission denied` | run `chmod +x run_mac_linux.sh` once, or start it with `bash run_mac_linux.sh` |

More detail: `README.md` (how it works, accuracy results) and `docs/DEMO.md` (a guided
demo, scene by scene).
