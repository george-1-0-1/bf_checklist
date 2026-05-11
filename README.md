# Breakfast Check-in App

A small Streamlit app for hotel breakfast check-in.

## What it does

- Upload a breakfast PDF
- Extract guest name, room number, arrival date, departure date, and total guests
- Search by room number
- Mark rooms as checked in
- Keep the uploaded list active while the app stays open
- Download CSV and Excel reports at the end

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy free on Streamlit Community Cloud

1. Create a GitHub repo.
2. Upload `app.py` and `requirements.txt`.
3. Go to Streamlit Community Cloud.
4. Select the repo and choose `app.py`.
5. Deploy.
