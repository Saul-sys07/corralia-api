import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def fetch_all(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params or ())
    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return result

def fetch_one(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params or ())
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result

def execute(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    conn.commit()
    last_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return last_id

def execute_transaction(operations):
    """
    Ejecuta varias operaciones SQL dentro de una sola transacción.
    
    operations debe ser una lista de tuplas:
    [
        ("SQL ...", (params,)),
        ("SQL ...", (params,))
    ]
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        for sql, params in operations:
            cursor.execute(sql, params or ())

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        raise e

    finally:
        cursor.close()
        conn.close()