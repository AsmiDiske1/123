import calendar
import ctypes
import os
import sqlite3
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

DB_PATH = "epidemiologist.db"
DUE_SOON_DAYS = 30
DEFAULT_CATEGORY = "Без категории"
CATEGORY_OPTIONS = (
    DEFAULT_CATEGORY,
    "Прививка",
    "Исследование",
    "Медосмотр",
    "Другое",
)


def clamp_date(day: int, month: int, year: int) -> tuple[int, int, int]:
    month = max(1, min(month, 12))
    year = max(1, year)
    last_day = calendar.monthrange(year, month)[1]
    day = max(1, min(day, last_day))
    return day, month, year


def normalize_date_value(value: str) -> str | None:
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) != 8:
        return None
    day = int(digits[:2])
    month = int(digits[2:4])
    year = int(digits[4:])
    day, month, year = clamp_date(day, month, year)
    return f"{day:02d}.{month:02d}.{year:04d}"


def attach_date_placeholder(entry: ttk.Entry, variable: tk.StringVar) -> None:
    placeholder = "ДД.ММ.ГГГГ"
    if not variable.get():
        variable.set(placeholder)

    def on_focus_in(_: tk.Event) -> None:
        if variable.get() == placeholder:
            variable.set("")

    def on_focus_out(_: tk.Event) -> None:
        current = variable.get().strip()
        if not current:
            variable.set(placeholder)
            return
        normalized = normalize_date_value(current)
        if normalized:
            variable.set(normalized)

    def on_key_release(_: tk.Event) -> None:
        value = entry.get()
        if value == placeholder:
            return
        digits = "".join(char for char in value if char.isdigit())
        if len(digits) > 8:
            digits = digits[:8]
        parts = []
        if len(digits) >= 2:
            parts.append(digits[:2])
        elif digits:
            parts.append(digits)
        if len(digits) >= 4:
            parts.append(digits[2:4])
        elif len(digits) > 2:
            parts.append(digits[2:])
        if len(digits) > 4:
            parts.append(digits[4:])
        formatted = ".".join(parts)
        if formatted != value:
            variable.set(formatted)
            entry.icursor(tk.END)

    entry.bind("<FocusIn>", on_focus_in)
    entry.bind("<FocusOut>", on_focus_out)
    entry.bind("<KeyRelease>", on_key_release)


@dataclass
class Record:
    record_id: int
    person: str
    item: str
    category: str
    due_date: date
    notes: str


class EpidemiologistTracker(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Контроль прививок и медосмотров")
        self.geometry("1120x620")
        self.minsize(1040, 600)

        self.connection = sqlite3.connect(DB_PATH)
        self._init_db()

        self._sort_ascending = True
        self._build_ui()
        self._load_records()

    def _init_db(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person TEXT NOT NULL,
                    item TEXT NOT NULL,
                    category TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    notes TEXT
                )
                """
            )

    def _build_ui(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=12, pady=(12, 4))

        title = ttk.Label(
            header,
            text="Контроль сроков: прививки, исследования и медосмотры",
            font=("Segoe UI", 14, "bold"),
        )
        title.pack(side=tk.LEFT)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=12, pady=4)

        ttk.Button(button_frame, text="Изменить", command=self._open_edit_dialog).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Удалить", command=self._delete_record).pack(
            side=tk.LEFT
        )

        legend = ttk.Label(
            button_frame,
            text="Легенда: красный — просрочено, жёлтый — скоро истекает",
        )
        legend.pack(side=tk.RIGHT)

        columns = ("item", "category", "due_date", "status", "notes")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="tree headings",
            height=18,
        )
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 8))

        self.tree.heading(
            "#0",
            text="Сотрудник / группа",
            command=self._toggle_person_sort,
        )
        self.tree.heading("item", text="Название")
        self.tree.heading("category", text="Категория")
        self.tree.heading("due_date", text="Срок до")
        self.tree.heading("status", text="Статус")
        self.tree.heading("notes", text="Примечание")

        self.tree.column("#0", width=180)
        self.tree.column("item", width=200)
        self.tree.column("category", width=140)
        self.tree.column("due_date", width=100, anchor=tk.CENTER)
        self.tree.column("status", width=140, anchor=tk.CENTER)
        self.tree.column("notes", width=220)

        self.tree.tag_configure("overdue", background="#f8d7da")
        self.tree.tag_configure("due_soon", background="#fff3cd")
        self.tree.tag_configure("ok", background="#e7f5ff")

        form_frame = ttk.LabelFrame(self, text="Новая запись", padding=12)
        form_frame.pack(fill=tk.X, padx=12, pady=(0, 12))

        self.person_var = tk.StringVar()
        self.item_var = tk.StringVar()
        self.category_var = tk.StringVar(value=DEFAULT_CATEGORY)
        self.date_var = tk.StringVar()
        self.notes_var = tk.StringVar()

        ttk.Label(form_frame, text="Сотрудник / группа").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(form_frame, textvariable=self.person_var, width=28).grid(
            row=1, column=0, padx=(0, 12), sticky=tk.W
        )

        ttk.Label(form_frame, text="Название").grid(row=0, column=1, sticky=tk.W)
        ttk.Entry(form_frame, textvariable=self.item_var, width=28).grid(
            row=1, column=1, padx=(0, 12), sticky=tk.W
        )

        ttk.Label(form_frame, text="Категория").grid(row=0, column=2, sticky=tk.W)
        category_combo = ttk.Combobox(
            form_frame,
            textvariable=self.category_var,
            values=CATEGORY_OPTIONS,
            width=24,
            state="readonly",
        )
        category_combo.grid(row=1, column=2, padx=(0, 12), sticky=tk.W)

        ttk.Label(form_frame, text="Срок (ДД.ММ.ГГГГ)").grid(
            row=0, column=3, sticky=tk.W
        )
        date_entry = ttk.Entry(form_frame, textvariable=self.date_var, width=18)
        date_entry.grid(row=1, column=3, padx=(0, 12), sticky=tk.W)
        attach_date_placeholder(date_entry, self.date_var)

        ttk.Label(form_frame, text="Примечание").grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(form_frame, textvariable=self.notes_var, width=30).grid(
            row=1, column=4, sticky=tk.W
        )

        ttk.Button(form_frame, text="Добавить", command=self._handle_add).grid(
            row=1, column=5, padx=(12, 0), sticky=tk.W
        )

    def _load_records(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        order = "ASC" if self._sort_ascending else "DESC"
        cursor = self.connection.execute(
            f"""
            SELECT id, person, item, category, due_date, notes
            FROM records
            ORDER BY person {order}, item ASC
            """
        )
        person_nodes: dict[str, str] = {}
        for row in cursor.fetchall():
            record = Record(
                record_id=row[0],
                person=row[1],
                item=row[2],
                category=row[3],
                due_date=date.fromisoformat(row[4]),
                notes=row[5] or "",
            )
            status_label, tag = self._status_for(record.due_date)
            if record.person not in person_nodes:
                parent_id = f"person:{record.person}"
                person_nodes[record.person] = parent_id
                self.tree.insert(
                    "",
                    tk.END,
                    iid=parent_id,
                    text=record.person,
                    values=("", "", "", "", ""),
                )
            self.tree.insert(
                person_nodes[record.person],
                tk.END,
                iid=f"record:{record.record_id}",
                text="",
                values=(
                    record.item,
                    record.category,
                    record.due_date.strftime("%d.%m.%Y"),
                    status_label,
                    record.notes,
                ),
                tags=(tag,),
            )
            self.tree.item(person_nodes[record.person], open=True)

    def _toggle_person_sort(self) -> None:
        self._sort_ascending = not self._sort_ascending
        self._load_records()

    def _status_for(self, due_date: date) -> tuple[str, str]:
        today = date.today()
        if due_date < today:
            return "Просрочено", "overdue"
        if due_date <= today + timedelta(days=DUE_SOON_DAYS):
            return f"Скоро истекает ({DUE_SOON_DAYS} дн.)", "due_soon"
        return "В норме", "ok"

    def _handle_add(self) -> None:
        payload = RecordInput(
            person=self.person_var.get().strip(),
            item=self.item_var.get().strip(),
            category=self.category_var.get().strip(),
            due_date=self.date_var.get().strip(),
            notes=self.notes_var.get().strip(),
        )
        parsed_date = self._validate_payload(payload)
        if parsed_date is None:
            return
        payload.due_date = parsed_date.isoformat()
        self._insert_record(payload)
        self.person_var.set("")
        self.item_var.set("")
        self.category_var.set(DEFAULT_CATEGORY)
        self.date_var.set("")
        self.notes_var.set("")

    @staticmethod
    def _parse_date(value: str) -> date | None:
        for fmt in ("%d.%m.%Y",):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _validate_payload(self, payload: "RecordInput") -> date | None:
        missing_fields = []
        if not payload.person:
            missing_fields.append("сотрудник/группа")
        if not payload.item:
            missing_fields.append("название")
        if not payload.category:
            missing_fields.append("категория")
        if not payload.due_date or payload.due_date == "ДД.ММ.ГГГГ":
            missing_fields.append("срок")
        if missing_fields:
            messagebox.showwarning(
                "Проверка",
                "Заполните поля: " + ", ".join(missing_fields) + ".",
            )
            return None
        normalized = normalize_date_value(payload.due_date) or payload.due_date
        payload.due_date = normalized
        parsed_date = self._parse_date(payload.due_date)
        if parsed_date is None:
            messagebox.showwarning(
                "Проверка",
                "Введите дату в формате ДД.ММ.ГГГГ.",
            )
            return None
        if parsed_date.year < 2000 or parsed_date.year > 2100:
            messagebox.showwarning(
                "Проверка", "Проверьте год даты срока действия."
            )
            return None
        return parsed_date

    def _insert_record(self, payload: "RecordInput") -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO records (person, item, category, due_date, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.person,
                    payload.item,
                    payload.category,
                    payload.due_date,
                    payload.notes,
                ),
            )
        self._load_records()

    def _open_edit_dialog(self) -> None:
        record_id = self._selected_record_id()
        if record_id is None:
            messagebox.showinfo("Выбор записи", "Выберите запись для изменения.")
            return
        cursor = self.connection.execute(
            "SELECT person, item, category, due_date, notes FROM records WHERE id = ?",
            (record_id,),
        )
        row = cursor.fetchone()
        if not row:
            messagebox.showerror("Ошибка", "Запись не найдена.")
            return
        due_date = date.fromisoformat(row[3]).strftime("%d.%m.%Y")
        EditDialog(
            self,
            record_id,
            RecordInput(
                person=row[0],
                item=row[1],
                category=row[2],
                due_date=due_date,
                notes=row[4] or "",
            ),
        )

    def _update_record(self, record_id: int, payload: "RecordInput") -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE records
                SET person = ?, item = ?, category = ?, due_date = ?, notes = ?
                WHERE id = ?
                """,
                (
                    payload.person,
                    payload.item,
                    payload.category,
                    payload.due_date,
                    payload.notes,
                    record_id,
                ),
            )
        self._load_records()

    def _delete_record(self) -> None:
        record_id = self._selected_record_id()
        if record_id is None:
            messagebox.showinfo("Выбор записи", "Выберите запись для удаления.")
            return
        if not messagebox.askyesno(
            "Подтверждение", "Удалить выбранную запись?"
        ):
            return
        with self.connection:
            self.connection.execute("DELETE FROM records WHERE id = ?", (record_id,))
        self._load_records()

    def _selected_record_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        selected = selection[0]
        if selected.startswith("person:"):
            return None
        if selected.startswith("record:"):
            return int(selected.split("record:", 1)[1])
        return None

    def destroy(self) -> None:
        self.connection.close()
        super().destroy()


@dataclass
class RecordInput:
    person: str
    item: str
    category: str
    due_date: str
    notes: str


class EditDialog(tk.Toplevel):
    def __init__(self, parent: EpidemiologistTracker, record_id: int, data: RecordInput) -> None:
        super().__init__(parent)
        self.title("Изменить запись")
        self.resizable(False, False)
        self.parent = parent
        self.record_id = record_id
        self.data = data

        self._build_form()
        self.grab_set()
        self.transient(parent)

    def _build_form(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        self.person_var = tk.StringVar(value=self.data.person)
        self.item_var = tk.StringVar(value=self.data.item)
        self.category_var = tk.StringVar(value=self.data.category)
        self.date_var = tk.StringVar(value=self.data.due_date)
        self.notes_var = tk.StringVar(value=self.data.notes)

        ttk.Label(frame, text="Сотрудник / группа").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.person_var, width=40).grid(
            row=1, column=0, columnspan=2, sticky=tk.W
        )

        ttk.Label(frame, text="Название").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.item_var, width=40).grid(
            row=3, column=0, columnspan=2, sticky=tk.W
        )

        ttk.Label(frame, text="Категория").grid(row=4, column=0, sticky=tk.W)
        category_combo = ttk.Combobox(
            frame,
            textvariable=self.category_var,
            values=CATEGORY_OPTIONS,
            width=38,
            state="readonly",
        )
        category_combo.grid(row=5, column=0, columnspan=2, sticky=tk.W)

        ttk.Label(frame, text="Срок (ДД.ММ.ГГГГ)").grid(row=6, column=0, sticky=tk.W)
        date_entry = ttk.Entry(frame, textvariable=self.date_var, width=20)
        date_entry.grid(row=7, column=0, sticky=tk.W)
        attach_date_placeholder(date_entry, self.date_var)

        ttk.Label(frame, text="Примечание").grid(row=8, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.notes_var, width=40).grid(
            row=9, column=0, columnspan=2, sticky=tk.W
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=10, column=0, columnspan=2, pady=(12, 0), sticky=tk.E)

        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(button_frame, text="Сохранить", command=self._handle_submit).pack(
            side=tk.RIGHT
        )

    def _handle_submit(self) -> None:
        payload = RecordInput(
            person=self.person_var.get().strip(),
            item=self.item_var.get().strip(),
            category=self.category_var.get().strip(),
            due_date=self.date_var.get().strip(),
            notes=self.notes_var.get().strip(),
        )
        parsed_date = self.parent._validate_payload(payload)
        if parsed_date is None:
            return
        payload.due_date = parsed_date.isoformat()
        self.parent._update_record(self.record_id, payload)
        self.destroy()


if __name__ == "__main__":
    if sys.platform == "win32":
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if console_window:
            ctypes.windll.user32.ShowWindow(console_window, 0)
    if sys.platform == "win32" and sys.executable.lower().endswith("python.exe"):
        pythonw = sys.executable[:-10] + "pythonw.exe"
        if os.path.exists(pythonw):
            subprocess.Popen([pythonw, __file__, *sys.argv[1:]])
            raise SystemExit(0)
    app = EpidemiologistTracker()
    app.mainloop()
