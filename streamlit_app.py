import streamlit as st
import sqlite3
from datetime import date, datetime
import pandas as pd
import time 
import re 
from typing import Union

# --- PUSTAKA KHUSUS SCANNER KAMERA ---
from streamlit_webrtc import webrtc_streamer, WebRtcMode, VideoProcessorBase
import av
from PIL import Image
from pyzbar.pyzbar import decode

# --- KONFIGURASI DAN INISIALISASI ---
DB_FILE = "kantin_staf.db" 
ADMIN_DEPARTEMEN_NAME = "Admin_Akses" 
ADMIN_BARCODE_ID = "9999Z"
ADMIN_NAMA = "Admin Master"
DEFAULT_DEPARTEMEN = ["Produksi", "HRD", "Keuangan", "IT", "Marketing", "Gudang", "Umum", ADMIN_DEPARTEMEN_NAME, "Tidak Ditentukan"]

def initialize_session_state():
    """Memastikan semua kunci st.session_state ada sebelum digunakan."""
    if 'mode' not in st.session_state:
        st.session_state['mode'] = 'Scanner' 
    if 'is_admin_logged_in' not in st.session_state:
        st.session_state['is_admin_logged_in'] = False
    if 'processing' not in st.session_state:
        st.session_state['processing'] = False

def get_db_connection():
    """Membuka koneksi database dengan row_factory untuk akses kolom bernama."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Membuat tabel staf, transaksi, dan departemen, serta data dummy jika belum ada."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Membuat Tabel Staf 
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staf (
            id INTEGER PRIMARY KEY,
            barcode_id TEXT UNIQUE NOT NULL,
            nama TEXT NOT NULL,
            departemen TEXT,  
            jatah_harian INTEGER DEFAULT 1
        )
    """)
    
    # Membuat Tabel Transaksi 
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY,
            barcode_id TEXT NOT NULL,
            waktu_transaksi TIMESTAMP NOT NULL,
            status_valid BOOLEAN NOT NULL 
        )
    """)
    
    # Membuat Tabel Departemen
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS departemen (
            id INTEGER PRIMARY KEY,
            nama_departemen TEXT UNIQUE NOT NULL
        )
    """)
    conn.commit()

    # Tambah Data Dummy Departemen
    for dept in DEFAULT_DEPARTEMEN:
        try:
            cursor.execute("INSERT INTO departemen (nama_departemen) VALUES (?)", (dept,))
        except sqlite3.IntegrityError:
            pass 
    conn.commit()
    
    # Tambah Data Dummy Staf (Hanya jika tabel kosong)
    cursor.execute("SELECT COUNT(*) FROM staf")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO staf (barcode_id, nama, departemen, jatah_harian) VALUES (?, ?, ?, ?)", 
                       ('1001A', 'Budi Santoso', 'Produksi', 1))
        cursor.execute("INSERT INTO staf (barcode_id, nama, departemen, jatah_harian) VALUES (?, ?, ?, ?)", 
                       ('2002B', 'Siti Aminah', 'HRD', 1)) 
        conn.commit()

    # --- VERIFIKASI ID ADMIN SELALU ADA ---
    cursor.execute("SELECT COUNT(*) FROM staf WHERE barcode_id = ?", (ADMIN_BARCODE_ID,))
    if cursor.fetchone()[0] == 0:
        try:
            cursor.execute("INSERT INTO staf (barcode_id, nama, departemen, jatah_harian) VALUES (?, ?, ?, ?)", 
                           (ADMIN_BARCODE_ID, ADMIN_NAMA, ADMIN_DEPARTEMEN_NAME, 0)) 
            conn.commit()
        except sqlite3.IntegrityError:
            pass
    # --- AKHIR VERIFIKASI ID ADMIN ---
    
    conn.close()

# --- FUNGSI WEBRTC: PEMROSESAN BARCODE DARI KAMERA ---

class BarcodeProcessor(VideoProcessorBase):
    """Kelas untuk memproses frame video dan mendeteksi barcode/QR code."""
    
    def __init__(self):
        self.scanned_id: Union[str, None] = None
        self.last_scan_time: float = 0
        self.debounce_period: float = 3.0 
        
    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        img = frame.to_ndarray(format="bgr24")
        decoded_objects = decode(Image.fromarray(img))
        current_time = time.time()
        
        for obj in decoded_objects:
            barcode_data = obj.data.decode("utf-8")
            
            if (self.scanned_id is None) and (current_time - self.last_scan_time > self.debounce_period):
                self.scanned_id = barcode_data
                self.last_scan_time = current_time
                
        return frame
        
# --- FUNGSI LOGOUT & CRUD (Sudah Diperbaiki dengan 'finally') ---

def logout_admin():
    """Reset state login."""
    st.session_state['is_admin_logged_in'] = False
    st.session_state['mode'] = 'Scanner'
    if 'mode_radio_selection' in st.session_state:
        del st.session_state['mode_radio_selection']
    st.rerun()

def get_departemen_list():
    conn = get_db_connection()
    dept_data = conn.execute("SELECT nama_departemen FROM departemen ORDER BY nama_departemen").fetchall()
    conn.close()
    return [row['nama_departemen'] for row in dept_data]

def tambah_departemen(nama):
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO departemen (nama_departemen) VALUES (?)", (nama,))
        conn.commit()
        return True, f"✅ Departemen '{nama}' berhasil ditambahkan."
    except sqlite3.IntegrityError:
        return False, f"❌ Gagal: Departemen '{nama}' sudah ada."
    finally:
        conn.close()

def hapus_departemen(nama):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if nama == ADMIN_DEPARTEMEN_NAME or nama == "Tidak Ditentukan":
            return False, f"❌ Gagal: Departemen '{nama}' tidak dapat dihapus."

        cursor.execute("UPDATE staf SET departemen = 'Tidak Ditentukan' WHERE departemen = ?", (nama,))
        staf_affected = cursor.rowcount
        cursor.execute("DELETE FROM departemen WHERE nama_departemen = ?", (nama,))
        
        conn.commit()
        return True, f"✅ Departemen '{nama}' berhasil dihapus. ({staf_affected} staf diperbarui)."
    except Exception as e:
        conn.rollback()
        return False, f"❌ Terjadi kesalahan saat menghapus departemen: {e}"
    finally:
        conn.close()

def tambah_staf(barcode_id, nama, departemen, jatah=1):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO staf (barcode_id, nama, departemen, jatah_harian) VALUES (?, ?, ?, ?)",
            (barcode_id, nama, departemen, jatah)
        )
        conn.commit()
        return True, f"✅ Staf {nama} ({barcode_id}) berhasil ditambahkan."
    except sqlite3.IntegrityError:
        return False, f"❌ Gagal: Barcode ID '{barcode_id}' sudah terdaftar."
    finally:
        conn.close() 

def edit_staf(barcode_id, nama, departemen):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE staf SET nama = ?, departemen = ? WHERE barcode_id = ?",
            (nama, departemen, barcode_id)
        )
        conn.commit()
        
        if cursor.rowcount > 0: 
            return True, f"✅ Data staf {barcode_id} berhasil diperbarui."
        else:
            return False, f"❌ Gagal: Barcode ID '{barcode_id}' tidak ditemukan."
            
    except Exception as e:
        conn.rollback()
        return False, f"❌ Terjadi kesalahan saat mengedit staf: {e}"
        
    finally:
        conn.close()

def hapus_staf(barcode_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if barcode_id == ADMIN_BARCODE_ID:
            return False, f"❌ Gagal: Barcode Admin ({ADMIN_BARCODE_ID}) tidak dapat dihapus."
            
        cursor.execute("DELETE FROM transaksi WHERE barcode_id = ?", (barcode_id,))
        transaksi_count = cursor.rowcount
        cursor.execute("DELETE FROM staf WHERE barcode_id = ?", (barcode_id,))
        conn.commit()
        
        if cursor.rowcount > 0:
            return True, f"✅ Staf {barcode_id} dan {transaksi_count} transaksi terkait berhasil dihapus."
        else:
            return False, f"❌ Gagal: Barcode ID '{barcode_id}' tidak ditemukan."
            
    except Exception as e:
        conn.rollback()
        return False, f"❌ Terjadi kesalahan saat menghapus staf: {e}"
    finally:
        conn.close()

def get_staf_by_barcode(barcode_id):
    conn = get_db_connection()
    staf = conn.execute("SELECT barcode_id, nama, departemen, jatah_harian FROM staf WHERE barcode_id = ?", (barcode_id,)).fetchone()
    conn.close()
    return staf

def tampil_data_staf():
    conn = get_db_connection()
    staf_data = conn.execute("SELECT barcode_id, nama, departemen, jatah_harian FROM staf ORDER BY nama").fetchall()
    conn.close()
    return pd.DataFrame([dict(row) for row in staf_data])

# --- FUNGSI get_all_transaksi (Stabil) ---
def get_all_transaksi(departemen_filter=None, start_date=None, end_date=None):
    conn = get_db_connection()
    query = """
        SELECT T.waktu_transaksi, S.nama, S.departemen, T.barcode_id, T.status_valid
        FROM transaksi AS T 
        JOIN staf AS S ON T.barcode_id = S.barcode_id
    """
    params = []
    
    where_clauses = []
    
    if departemen_filter and departemen_filter != "Semua Departemen":
        where_clauses.append("S.departemen = ?")
        params.append(departemen_filter)
    
    if start_date:
        where_clauses.append("DATE(T.waktu_transaksi) >= ?")
        params.append(start_date) 
    
    if end_date:
        where_clauses.append("DATE(T.waktu_transaksi) <= ?")
        params.append(end_date) 
        
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
        
    query += " ORDER BY T.waktu_transaksi DESC"
        
    transaksi = conn.execute(query, params).fetchall()
    conn.close()
    
    # Definisikan Kolom yang Diharapkan
    expected_columns = ['Waktu', 'Nama Staf', 'Departemen', 'ID Barcode', 'Status']
    
    data = []
    for row in transaksi:
        data.append({
            'Waktu': row['waktu_transaksi'], 
            'Nama Staf': row['nama'], 
            'Departemen': row['departemen'],
            'ID Barcode': row['barcode_id'],
            'Status': 'VALID' if row['status_valid'] else 'BATAS (Ditolak)'
        })
        
    # Pastikan DataFrame dikembalikan dengan kolom yang benar, meskipun kosong
    if not data:
        return pd.DataFrame(data, columns=expected_columns) 

    return pd.DataFrame(data)

def get_jatah_harian_staf(departemen_filter=None):
    conn = get_db_connection()
    today_str = date.today().strftime('%Y-%m-%d')
    
    query = f"""
        SELECT 
            S.barcode_id, 
            S.nama, 
            S.departemen,  
            S.jatah_harian, 
            COALESCE(T.jumlah_ambil, 0) as sudah_ambil
        FROM staf AS S
        LEFT JOIN (
            SELECT barcode_id, COUNT(*) as jumlah_ambil 
            FROM transaksi
            WHERE status_valid = 1 AND DATE(waktu_transaksi) = '{today_str}'
            GROUP BY barcode_id
        ) AS T ON S.barcode_id = T.barcode_id
    """
    params = []
    if departemen_filter and departemen_filter != "Semua Departemen":
        query += " WHERE S.departemen = ?"
        params.append(departemen_filter)
        
    query += " ORDER BY S.nama"
    
    data = conn.execute(query, params).fetchall()
    conn.close()
    
    df_data = []
    for row in data:
        row_dict = dict(row)
        sudah_ambil = row_dict['sudah_ambil']
        jatah_harian = row_dict['jatah_harian']
        sisa_jatah = jatah_harian - sudah_ambil
        
        df_data.append({
            'Nama Staf': row_dict['nama'],
            'Departemen': row_dict['departemen'],
            'ID Barcode': row_dict['barcode_id'],
            'Jatah Harian': jatah_harian,
            'Sudah Diambil': sudah_ambil,
            'Sisa Jatah': sisa_jatah,
            'Status': 'Selesai' if sisa_jatah <= 0 else 'Tersedia'
        })
    
    return pd.DataFrame(df_data)

# --- FUNGSI UTAMA SCANNING (LOGIKA LOGIN & TRANSAKSI) ---

def process_barcode_scan(barcode_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = date.today().strftime('%Y-%m-%d')
    
    staf = cursor.execute("SELECT * FROM staf WHERE barcode_id = ?", (barcode_id,)).fetchone()
    
    if not staf:
        conn.close()
        return "Gagal", f"❌ ID Staf '{barcode_id}' tidak terdaftar!"

    nama_staf = staf['nama']
    departemen_staf = staf['departemen']

    # 1. CEK HAK AKSES ADMIN
    if departemen_staf == ADMIN_DEPARTEMEN_NAME:
        conn.close()
        st.session_state['is_admin_logged_in'] = True
        st.session_state['mode'] = 'Admin' 
        
        if 'mode_radio_selection' in st.session_state:
            del st.session_state['mode_radio_selection'] 

        st.rerun() 
        return "Sukses_Admin", f"✅ Akses Admin untuk {nama_staf} berhasil."

    # 2. LOGIKA TRANSAKSI MAKANAN (untuk staf biasa)
    cursor.execute("""
        SELECT COUNT(id) FROM transaksi 
        WHERE barcode_id = ? AND status_valid = 1 
        AND DATE(waktu_transaksi) = ?
    """, (barcode_id, today_str))
    
    transaksi_hari_ini = cursor.fetchone()[0]
    jatah_staf = staf['jatah_harian']
    
    if transaksi_hari_ini >= jatah_staf:
        # Catat transaksi Ditolak (status_valid = 0)
        cursor.execute("INSERT INTO transaksi (barcode_id, waktu_transaksi, status_valid) VALUES (?, ?, ?)",
                       (barcode_id, datetime.now(), 0))
        conn.commit()
        conn.close()
        return "Peringatan", f"⚠️ {nama_staf} ({departemen_staf}) sudah mengambil {transaksi_hari_ini}/{jatah_staf} jatah harian!"

    # Catat transaksi Diterima (status_valid = 1)
    cursor.execute("INSERT INTO transaksi (barcode_id, waktu_transaksi, status_valid) VALUES (?, ?, ?)",
                   (barcode_id, datetime.now(), 1))
    conn.commit()
    conn.close()
    return "Sukses", f"✅ Makanan untuk {nama_staf} ({departemen_staf}) berhasil dicatat. Jatah tersisa: {jatah_staf - (transaksi_hari_ini + 1)}"


# =====================================================================
# --- LOGIKA TAMPILAN UTAMA STREAMLIT ---
# =====================================================================

initialize_session_state() 
init_db() 

st.title("🍽️ Sistem Scan Kantin Staf")

# --- MODE SWITCHER (SIDEBAR) ---
st.sidebar.title("Navigasi Aplikasi")

if st.session_state['is_admin_logged_in']:
    mode_options = ('Scanner/Kantin', 'Admin Input & Laporan')
    default_mode_index = 1 if st.session_state['mode'] == 'Admin' else 0
else:
    mode_options = ('Scanner/Kantin',)
    default_mode_index = 0
    st.session_state['mode'] = 'Scanner' 

mode_selection = st.sidebar.radio(
    "Pilih Mode Aplikasi",
    mode_options,
    index=default_mode_index, 
    key='mode_radio_selection' 
)

st.session_state['mode'] = 'Scanner' if mode_selection == 'Scanner/Kantin' else 'Admin'

st.markdown("---")

# --- Tombol Logout (di Sidebar) ---
if st.session_state['is_admin_logged_in']:
    st.sidebar.button("Keluar (Logout Admin)", on_click=logout_admin, type="secondary")
    
st.sidebar.markdown("---")


# ===================================================
# 1. SCANNER / KANTIN VIEW (DENGAN KAMERA SCANNER)
# ===================================================
if st.session_state['mode'] == 'Scanner':
    
    st.header("Mode: Operasional Kantin (Scan ID)")
    st.subheader("Area Pemindaian Barcode via Kamera/Webcam")
    
    st.caption(f"Arahkan kamera ke Barcode/QR Code. Scan ID **{ADMIN_BARCODE_ID}** untuk Akses Admin.")

    webrtc_ctx = webrtc_streamer(
        key="barcode-scanner",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        video_processor_factory=BarcodeProcessor,
        media_stream_constraints={
            "video": True, 
            "audio": False
        },
        async_processing=True,
    )
    
    output_placeholder = st.empty() 
    scanned_id = None

    if webrtc_ctx.video_processor:
        scanned_id = webrtc_ctx.video_processor.scanned_id
        
        if scanned_id:
            webrtc_ctx.video_processor.scanned_id = None 
            
            status, pesan = process_barcode_scan(scanned_id.strip())
            
            if status == "Sukses":
                output_placeholder.success(pesan)
            elif status == "Peringatan":
                output_placeholder.warning(pesan)
            elif status == "Sukses_Admin":
                pass 
            else: 
                output_placeholder.error(pesan)
            
            if status != "Sukses_Admin":
                time.sleep(1.5) 
                st.rerun() 
        else:
            output_placeholder.info("Menunggu Barcode/QR Code untuk dipindai...")
            
    # --- Opsional: Text Input sebagai Fallback ---
    st.markdown("---")
    st.caption("Atau, Masukkan ID secara Manual:")
    
    with st.form(key='manual_scan_form'):
        manual_barcode_input = st.text_input(
            "Masukkan Barcode ID Staf (Manual):", 
            placeholder="Ketik ID Barcode di sini..."
        )
        submit_manual = st.form_submit_button(label='Proses Manual')
        
    if submit_manual and manual_barcode_input:
        status, pesan = process_barcode_scan(manual_barcode_input.strip())
        
        if status == "Sukses":
            output_placeholder.success(pesan)
        elif status == "Peringatan":
            output_placeholder.warning(pesan)
        elif status == "Sukses_Admin":
            pass 
        else: 
            output_placeholder.error(pesan)
        
        if status != "Sukses_Admin":
            time.sleep(1.5) 
            st.rerun() 


# ===================================================
# 2. ADMIN VIEW (KONTEN)
# ===================================================
elif st.session_state['mode'] == 'Admin':
    
    st.header("Mode: Administrasi Data & Laporan")
    
    if not st.session_state['is_admin_logged_in']:
        st.warning(f"Akses ditolak. Silakan scan Barcode ID Admin ({ADMIN_BARCODE_ID}) di Mode Scanner.")
        
    else:
        DEPARTEMEN_LIST_DYNAMIC = get_departemen_list()
        
        tab1, tab2, tab3, tab4 = st.tabs(["Manajemen Staf (CRUD)", "Manajemen Departemen", "Laporan Jatah Harian", "Laporan Semua Transaksi"])

        # === TAB 1: MANAJEMEN STAF (CREATE, READ, UPDATE, DELETE) ===
        with tab1:
            st.subheader("Kelola Data Staf")
            
            crud_tab = st.selectbox("Pilih Operasi:", 
                                    ["Tambah Staf Baru", "Edit Staf", "Hapus Staf"],
                                    key="crud_select")
            st.markdown("---")
            
            if crud_tab == "Tambah Staf Baru":
                st.caption("Tambah data staf baru. Jatah Harian ditetapkan 1x per hari.")
                
                with st.form(key='tambah_staf_form', clear_on_submit=True):
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        new_barcode = st.text_input("Barcode ID:")
                    with col2:
                        new_jatah = 1
                        st.write(f"Jatah Harian: **{new_jatah}**")
                    
                    new_nama = st.text_input("Nama Staf Lengkap:")
                    
                    dept_options_for_staf = [d for d in DEPARTEMEN_LIST_DYNAMIC if d != ADMIN_DEPARTEMEN_NAME and d != "Tidak Ditentukan"]

                    if not dept_options_for_staf:
                        st.error("❌ Anda belum memiliki Departemen. Silakan tambah di tab Manajemen Departemen.")
                        new_departemen = None
                    else:
                        new_departemen = st.selectbox("Pilih Departemen/Divisi:", dept_options_for_staf)
                        
                    submit_admin = st.form_submit_button("Tambahkan Staf ke Database")
                    
                    if submit_admin:
                        if new_barcode and new_nama and new_departemen:
                            status, pesan = tambah_staf(new_barcode.strip(), new_nama.strip(), new_departemen, new_jatah)
                            if status:
                                st.success(pesan)
                                time.sleep(1) 
                                st.rerun() 
                            else:
                                st.error(pesan)
                        else:
                            st.warning("Barcode ID, Nama Staf, dan Departemen harus diisi.")
            
            elif crud_tab == "Edit Staf":
                st.caption("Cari staf berdasarkan Nama atau Barcode ID, lalu ubah data staf.")
                
                df_staf_all = tampil_data_staf()
                df_staf_all = df_staf_all[df_staf_all['departemen'] != ADMIN_DEPARTEMEN_NAME]

                if df_staf_all.empty:
                    st.info("Tidak ada data staf untuk diedit.")
                else:
                    df_staf_all['display'] = df_staf_all['nama'] + " (" + df_staf_all['barcode_id'] + ") - " + df_staf_all['departemen']
                    
                    search_query = st.text_input("Ketik Nama atau Barcode ID Staf untuk Mencari:", key="search_edit_staf").strip().lower()
                    
                    filtered_options = []
                    
                    if search_query:
                        filtered_df = df_staf_all[
                            (df_staf_all['nama'].str.lower().str.contains(search_query)) | 
                            (df_staf_all['barcode_id'].str.lower().str.contains(search_query))
                        ]
                        filtered_options = filtered_df['display'].tolist()
                        if not filtered_options:
                            st.warning("Staf tidak ditemukan.")
                    else:
                        filtered_options = df_staf_all['display'].tolist()

                    filtered_options.insert(0, "")
                    
                    selected_staf_display = st.selectbox(
                        "Pilih Staf dari Daftar/Hasil Pencarian:", 
                        filtered_options, 
                        key="edit_select_staf"
                    )
                    
                    st.markdown("---")

                    if selected_staf_display:
                        match = re.search(r'\((.*?)\)', selected_staf_display)
                        barcode_id = match.group(1) if match else None
                        
                        if barcode_id:
                            staf_data = get_staf_by_barcode(barcode_id)
                            
                            if staf_data:
                                available_departments = [d for d in DEPARTEMEN_LIST_DYNAMIC if d != ADMIN_DEPARTEMEN_NAME] 

                                with st.form(key='edit_staf_form'):
                                    
                                    st.text_input("Barcode ID (Tidak dapat diubah):", value=staf_data['barcode_id'], disabled=True)
                                    edited_nama = st.text_input("Nama Staf:", value=staf_data['nama'])
                                    
                                    try:
                                        default_index = available_departments.index(staf_data['departemen'])
                                    except ValueError:
                                        default_index = 0
                                        
                                    edited_departemen = st.selectbox("Departemen/Divisi:", available_departments, index=default_index)

                                    submit_edit = st.form_submit_button("Simpan Perubahan")
                                    
                                    if submit_edit:
                                        status, pesan = edit_staf(barcode_id, edited_nama.strip(), edited_departemen)
                                        if status:
                                            st.success(pesan)
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error(pesan)
                            else:
                                st.error("Data staf tidak ditemukan.")

            
            elif crud_tab == "Hapus Staf":
                st.caption("PERINGATAN: Menghapus staf akan menghapus SEMUA transaksi terkait.")
                
                df_staf_all = tampil_data_staf()
                df_staf_all = df_staf_all[df_staf_all['departemen'] != ADMIN_DEPARTEMEN_NAME]
                
                staf_options = [f"{row['nama']} ({row['barcode_id']})" for row in df_staf_all.to_dict('records')]
                staf_options.insert(0, "")

                selected_staf_del = st.selectbox("Pilih Staf yang Akan Dihapus:", staf_options, key="delete_select_staf")
                
                if selected_staf_del:
                    match = re.search(r'\((.*?)\)', selected_staf_del)
                    barcode_id = match.group(1) if match else None

                    if barcode_id:
                        staf_data = get_staf_by_barcode(barcode_id)
                        st.warning(f"Anda akan menghapus **{staf_data['nama']}** ({staf_data['departemen']}).")
                        
                        if st.button(f"Konfirmasi HAPUS Staf {barcode_id}", type="primary"):
                            status, pesan = hapus_staf(barcode_id)
                            if status:
                                st.success(pesan)
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(pesan)
                    else:
                        st.error("Silakan pilih staf yang valid.")


            st.markdown("---")
            st.subheader("Daftar Semua Staf")
            data_staf = tampil_data_staf()
            data_staf = data_staf[data_staf['departemen'] != ADMIN_DEPARTEMEN_NAME]
            
            if not data_staf.empty:
                # Perbaikan: Mengganti use_container_width=True menjadi width='stretch'
                st.dataframe(data_staf, width='stretch', 
                            column_order=("nama", "departemen", "barcode_id", "jatah_harian"),
                            column_config={
                                "nama": "Nama Staf",
                                "departemen": "Departemen/Divisi", 
                                "barcode_id": "ID Barcode",
                                "jatah_harian": "Jatah/Hari"
                            })
            else:
                st.info("Belum ada data staf yang tercatat.")

        # === TAB 2: MANAJEMEN DEPARTEMEN ===
        with tab2:
            st.subheader("Tambah/Hapus Departemen")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.caption("Tambah Departemen Baru")
                with st.form(key='form_add_dept', clear_on_submit=True):
                    new_dept_name = st.text_input("Nama Departemen:", placeholder="Misal: R&D")
                    if st.form_submit_button("Tambah"):
                        if new_dept_name:
                            status, pesan = tambah_departemen(new_dept_name.strip())
                            if status:
                                st.success(pesan)
                                st.rerun()
                            else:
                                st.error(pesan)
                        else:
                            st.warning("Nama departemen tidak boleh kosong.")
            
            with col2:
                st.caption("Hapus Departemen (Staf terkait akan disetel ke 'Tidak Ditentukan')")
                dept_options_for_del = [d for d in DEPARTEMEN_LIST_DYNAMIC if d not in (ADMIN_DEPARTEMEN_NAME, "Tidak Ditentukan")]
                
                if not dept_options_for_del:
                    st.info("Tidak ada departemen yang dapat dihapus.")
                else:
                    dept_to_delete = st.selectbox("Pilih Departemen untuk Dihapus:", dept_options_for_del, key="del_dept_select")
                    
                    if st.button(f"Konfirmasi Hapus Departemen {dept_to_delete}", type="primary"):
                        status, pesan = hapus_departemen(dept_to_delete)
                        if status:
                            st.success(pesan)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(pesan)
            
            st.markdown("---")
            st.subheader("Daftar Departemen Aktif")
            
            if DEPARTEMEN_LIST_DYNAMIC:
                display_dept = []
                for d in DEPARTEMEN_LIST_DYNAMIC:
                    catatan = ""
                    if d == ADMIN_DEPARTEMEN_NAME:
                        catatan = "Akses Admin (Tidak dapat dihapus)"
                    elif d == "Tidak Ditentukan":
                        catatan = "Staf tanpa departemen (Tidak dapat dihapus)"
                    else:
                        catatan = "-"
                    display_dept.append({"Departemen Aktif": d, "Catatan": catatan})

                df_dept = pd.DataFrame(display_dept)
                # Perbaikan: Mengganti use_container_width=True menjadi width='stretch'
                st.dataframe(df_dept, width='stretch')
            else:
                st.info("Tidak ada departemen yang tercatat.")

        # === TAB 3: LAPORAN JATAH HARIAN ===
        with tab3:
            st.subheader(f"Status Pengambilan Jatah Hari Ini ({date.today().strftime('%d-%m-%Y')})")
            
            filter_options = ["Semua Departemen"] + [d for d in DEPARTEMEN_LIST_DYNAMIC if d != ADMIN_DEPARTEMEN_NAME]
            filter_dept_jatah = st.selectbox("Filter berdasarkan Departemen:", filter_options, key="filter_jatah_dept")
            
            df_jatah = get_jatah_harian_staf(filter_dept_jatah)
            df_jatah = df_jatah[df_jatah['Departemen'] != ADMIN_DEPARTEMEN_NAME]

            if not df_jatah.empty:
                # Perbaikan: Mengganti use_container_width=True menjadi width='stretch'
                st.dataframe(df_jatah, width='stretch',
                             column_config={
                                 "Jatah Harian": st.column_config.NumberColumn(format="%d"),
                                 "Sudah Diambil": st.column_config.NumberColumn(format="%d"),
                                 "Sisa Jatah": st.column_config.NumberColumn(format="%d"),
                                 "Status": st.column_config.TextColumn("Status"),
                                 "Departemen": st.column_config.TextColumn("Departemen/Divisi")
                             })
                st.download_button(
                    label="📥 Download Data Jatah Harian",
                    data=df_jatah.to_csv(index=False).encode('utf-8'),
                    file_name=f'Laporan_Jatah_Harian_{date.today()}.csv',
                    mime='text/csv',
                )
            else:
                st.info(f"Tidak ada data staf atau transaksi untuk departemen '{filter_dept_jatah}' hari ini.")


        # === TAB 4: LAPORAN SEMUA TRANSAKSI (DENGAN FILTER TANGGAL) ===
        with tab4:
            st.subheader("Riwayat Semua Transaksi")

            filter_options = ["Semua Departemen"] + [d for d in DEPARTEMEN_LIST_DYNAMIC if d != ADMIN_DEPARTEMEN_NAME]
            
            col_filter, col_date_start, col_date_end = st.columns([1.5, 1, 1])
            
            with col_filter:
                filter_dept_transaksi = st.selectbox("Filter Departemen:", filter_options, key="filter_transaksi_dept")
            
            today = date.today()
            
            with col_date_start:
                start_tgl = st.date_input("Tanggal Awal:", value=today, key="start_transaksi_date")
                
            with col_date_end:
                end_tgl = st.date_input("Tanggal Akhir:", value=today, key="end_transaksi_date")
                
            if start_tgl > end_tgl:
                st.error("❌ Tanggal awal tidak boleh melebihi tanggal akhir. Silakan perbaiki rentang tanggal.")
            else:
                df_transaksi = get_all_transaksi(
                    departemen_filter=filter_dept_transaksi, 
                    start_date=start_tgl.strftime('%Y-%m-%d'), 
                    end_date=end_tgl.strftime('%Y-%m-%d')
                )
                
                df_transaksi = df_transaksi[df_transaksi['Departemen'] != ADMIN_DEPARTEMEN_NAME]

                if not df_transaksi.empty:
                    # Perbaikan: Mengganti use_container_width=True menjadi width='stretch'
                    st.dataframe(df_transaksi, width='stretch',
                                 column_config={
                                     "Waktu": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss")
                                 })
                    st.download_button(
                        label="📥 Download Riwayat Transaksi",
                        data=df_transaksi.to_csv(index=False).encode('utf-8'),
                        file_name=f'Riwayat_Transaksi_{start_tgl}_sampai_{end_tgl}.csv',
                        mime='text/csv',
                    )
                else:
                    st.info(f"Tidak ada transaksi tercatat pada rentang **{start_tgl.strftime('%d-%m-%Y')}** hingga **{end_tgl.strftime('%d-%m-%Y')}** untuk departemen '{filter_dept_transaksi}'.")