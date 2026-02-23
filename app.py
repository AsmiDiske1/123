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
MEDBOOK_ITEMS = [
    ("Прививка", "Корь"),
    ("Прививка", "Краснуха"),
    ("Прививка", "Паротит"),
    ("Прививка", "Дифтерия и столбняк"),
    ("Прививка", "Грипп"),
    ("Прививка", "Гепатит B"),
    ("Исследование", "ФЛГ (флюорография)"),
    ("Исследование", "RW (сифилис)"),
    ("Исследование", "ВИЧ"),
    ("Исследование", "HBsAg (гепатит B)"),
    ("Исследование", "Anti-HCV (гепатит C)"),
    ("Исследование", "Мазок на стафилококк"),
    ("Исследование", "Кишечные инфекции"),
    ("Исследование", "Гельминты/яйца глист"),
]


def clamp_date(day: int, month: int, year: int) -> tuple[int, int, int]:
    month = max(1, min(month, 12))
    year = max(1, year)
    last_day = calendar.monthrange(year, month)[1]
    day = max(1, min(day, last_day))
    return day, month, year


def normalize_date_value(value: str) -> str | None:
    value = value.strip()
    if "." in value:
        parts = [part for part in value.split(".") if part]
        if len(parts) < 3:
            return None
        day_part, month_part, year_part = parts[:3]
        if not (day_part.isdigit() and month_part.isdigit() and year_part.isdigit()):
            return None
        day = int(day_part.zfill(2))
        month = int(month_part.zfill(2))
        year = int(year_part.zfill(4))
    else:
        digits = "".join(char for char in value if char.isdigit())
        if len(digits) != 8:
            return None
        day = int(digits[:2])
        month = int(digits[2:4])
        year = int(digits[4:])
    day, month, year = clamp_date(day, month, year)
    return f"{day:02d}.{month:02d}.{year:04d}"


def attach_date_placeholder(
    entry: ttk.Entry, variable: tk.StringVar, use_placeholder: bool = True
) -> None:
    placeholder = "ДД.ММ.ГГГГ"
    if use_placeholder and not variable.get():
        variable.set(placeholder)

    def on_focus_in(_: tk.Event) -> None:
        if use_placeholder and variable.get() == placeholder:
            variable.set("")

    def on_focus_out(_: tk.Event) -> None:
        current = variable.get().strip()
        if not current:
            if use_placeholder:
                variable.set(placeholder)
            return
        normalized = normalize_date_value(current)
        if normalized:
            variable.set(normalized)

    def on_key_release(_: tk.Event) -> None:
        value = entry.get()
        if use_placeholder and value == placeholder:
            return
        if "." in value:
            raw_parts = value.split(".")
            parts: list[str] = []
            for idx, part in enumerate(raw_parts):
                if idx > 2:
                    break
                if not part:
                    parts.append(part)
                    continue
                if idx < 2 and len(part) == 1 and idx < len(raw_parts) - 1:
                    parts.append(f"0{part}")
                else:
                    parts.append(part)
            formatted = ".".join(parts)
        else:
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
        self._seed_if_empty()

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

    def _seed_if_empty(self) -> None:
        cursor = self.connection.execute("SELECT COUNT(*) FROM records")
        if cursor.fetchone()[0]:
            return
        today = date.today()
        samples = []
        for idx, (category, item) in enumerate(MEDBOOK_ITEMS):
            due_date = today + timedelta(days=15 + idx * 10)
            samples.append(("Иванов И.И.", item, category, due_date))
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO records (person, item, category, due_date, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (person, item, category, due_date.isoformat(), "пример")
                    for person, item, category, due_date in samples
                ],
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

        ttk.Button(button_frame, text="Добавить", command=self._open_add_dialog).pack(
            side=tk.LEFT, padx=(0, 6)
        )
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

        columns = ("item", "due_date", "status", "notes")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="tree",
            height=18,
        )
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 8))
        self.tree.bind("<Button-1>", self._handle_tree_click, add="+")

        self.tree.heading(
            "#0",
            text="Сотрудник / группа",
            command=self._toggle_person_sort,
        )
        self.tree.heading("item", text="Название")
        self.tree.heading("due_date", text="Срок до")
        self.tree.heading("status", text="Статус")
        self.tree.heading("notes", text="Примечание")

        self.tree.column("#0", width=180)
        self.tree.column("item", width=200)
        self.tree.column("due_date", width=100, anchor=tk.CENTER)
        self.tree.column("status", width=140, anchor=tk.CENTER)
        self.tree.column("notes", width=220)

        self.tree.tag_configure("overdue", background="#f2b8b5")
        self.tree.tag_configure("due_soon", background="#ffe08a")
        self.tree.tag_configure("ok", background="#e7f5ff")

        self._build_empty_state()

    def _build_empty_state(self) -> None:
        ttk.Label(
            self,
            text="Добавляйте записи через кнопку «Добавить».",
            foreground="#6c757d",
        ).pack(fill=tk.X, padx=12, pady=(0, 12))

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
        records_by_person: dict[str, list[Record]] = {}
        for row in cursor.fetchall():
            record = Record(
                record_id=row[0],
                person=row[1],
                item=row[2],
                category=row[3],
                due_date=date.fromisoformat(row[4]),
                notes=row[5] or "",
            )
            records_by_person.setdefault(record.person, []).append(record)

        for person, records in records_by_person.items():
            parent_id = f"person:{person}"
            person_nodes[person] = parent_id
            note_text = next((record.notes for record in records if record.notes), "-")
            overdue_count = 0
            due_soon_count = 0
            for record in records:
                today = date.today()
                if record.due_date < today:
                    overdue_count += 1
                elif record.due_date <= today + timedelta(days=DUE_SOON_DAYS):
                    due_soon_count += 1
            status_text = f"Просрочено: {overdue_count}" if overdue_count else "-"
            due_soon_text = (
                f"Подходит срок ревакцинации: {due_soon_count}"
                if due_soon_count
                else "-"
            )
            person_tag = ""
            if overdue_count:
                person_tag = "overdue"
            elif due_soon_count:
                person_tag = "due_soon"
            self.tree.insert(
                "",
                tk.END,
                iid=parent_id,
                text=person,
                values=("", "", status_text, due_soon_text),
                tags=(person_tag,) if person_tag else (),
            )
            self.tree.insert(
                parent_id,
                tk.END,
                iid=f"header:{person}",
                text="",
                values=("Название", "Срок до", "Статус", note_text),
            )

            latest_by_item: dict[str, Record] = {}
            for record in records:
                existing = latest_by_item.get(record.item)
                if existing is None or record.due_date > existing.due_date:
                    latest_by_item[record.item] = record

            required_items = {item for _, item in MEDBOOK_ITEMS}
            extra_items = [record.item for record in records if record.item not in required_items]

            for category, item_name in MEDBOOK_ITEMS:
                record = latest_by_item.get(item_name)
                if record:
                    status_label, tag = self._status_for(record.due_date)
                    due_date_text = record.due_date.strftime("%d.%m.%Y")
                    notes = "-"
                    iid = f"record:{record.record_id}"
                else:
                    status_label = "-"
                    tag = ""
                    due_date_text = "-"
                    notes = "-"
                    iid = f"missing:{person}:{item_name}"
                self.tree.insert(
                    parent_id,
                    tk.END,
                    iid=iid,
                    text="",
                    values=(
                        item_name,
                        due_date_text,
                        status_label,
                        notes,
                    ),
                    tags=(tag,) if tag else (),
                )

            for item_name in sorted(set(extra_items)):
                record = latest_by_item[item_name]
                status_label, tag = self._status_for(record.due_date)
                self.tree.insert(
                    parent_id,
                    tk.END,
                    iid=f"record:{record.record_id}",
                    text="",
                    values=(
                        item_name,
                        record.due_date.strftime("%d.%m.%Y"),
                        status_label,
                        "-",
                    ),
                    tags=(tag,),
                )

            self.tree.item(parent_id, open=False)

    def _toggle_person_sort(self) -> None:
        self._sort_ascending = not self._sort_ascending
        self._load_records()

    def _handle_tree_click(self, event: tk.Event) -> None:
        if not self.tree.identify_row(event.y):
            self.tree.selection_remove(self.tree.selection())

    def _status_for(self, due_date: date) -> tuple[str, str]:
        today = date.today()
        if due_date < today:
            days_overdue = (today - due_date).days
            return f"Просрочено ({days_overdue} дн.)", "overdue"
        days_left = (due_date - today).days
        if days_left <= DUE_SOON_DAYS:
            return f"Подходит срок ревакцинации ({days_left} дн.)", "due_soon"
        return "В норме", "ok"

    def _open_add_dialog(self) -> None:
        AddDialog(self)

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

    def _insert_records(self, payloads: list["RecordInput"]) -> None:
        if not payloads:
            return
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO records (person, item, category, due_date, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        payload.person,
                        payload.item,
                        payload.category,
                        payload.due_date,
                        payload.notes,
                    )
                    for payload in payloads
                ],
            )
        self._load_records()

    def _open_edit_dialog(self) -> None:
        person = self._selected_person()
        if not person:
            messagebox.showinfo("Выбор записи", "Выберите сотрудника для изменения.")
            return
        EditAllDialog(self, person)

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
        if selected.startswith("person:") or selected.startswith("header:"):
            return None
        if selected.startswith("record:"):
            return int(selected.split("record:", 1)[1])
        return None

    def _selected_person(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            return None
        selected = selection[0]
        if selected.startswith("person:"):
            return selected.split("person:", 1)[1]
        if selected.startswith("record:"):
            record_id = int(selected.split("record:", 1)[1])
            cursor = self.connection.execute(
                "SELECT person FROM records WHERE id = ?",
                (record_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        if selected.startswith("header:"):
            return selected.split("header:", 1)[1]
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


class AddDialog(tk.Toplevel):
    def __init__(self, parent: EpidemiologistTracker) -> None:
        super().__init__(parent)
        self.title("Добавить записи")
        self.resizable(False, False)
        self.parent = parent
        self.entries: dict[tuple[str, str], tk.StringVar] = {}

        self._build_form()
        self.grab_set()
        self.transient(parent)

    def _build_form(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Сотрудник / группа").grid(row=0, column=0, sticky=tk.W)
        self.person_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.person_var, width=40).grid(
            row=1, column=0, columnspan=3, sticky=tk.W
        )

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=2, column=0, columnspan=3, pady=(12, 0), sticky=tk.W)

        ttk.Label(list_frame, text="Название").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(list_frame, text="Срок (ДД.ММ.ГГГГ)").grid(
            row=0, column=1, sticky=tk.W
        )

        for index, (category, item_name) in enumerate(MEDBOOK_ITEMS, start=1):
            ttk.Label(list_frame, text=item_name).grid(
                row=index, column=0, sticky=tk.W, pady=2
            )
            date_var = tk.StringVar()
            date_entry = ttk.Entry(list_frame, textvariable=date_var, width=16)
            date_entry.grid(row=index, column=1, sticky=tk.W)
            attach_date_placeholder(date_entry, date_var, use_placeholder=False)
            self.entries[(category, item_name)] = date_var

        ttk.Label(frame, text="Примечание").grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        self.notes_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.notes_var, width=50).grid(
            row=4, column=0, columnspan=3, sticky=tk.W
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=(12, 0), sticky=tk.E)
        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(button_frame, text="Сохранить", command=self._handle_submit).pack(
            side=tk.RIGHT
        )

    def _handle_submit(self) -> None:
        person = self.person_var.get().strip()
        if not person:
            messagebox.showwarning("Проверка", "Заполните сотрудника/группу.")
            return
        payloads: list[RecordInput] = []
        for category, item_name in MEDBOOK_ITEMS:
            date_value = self.entries[(category, item_name)].get().strip()
            if not date_value or date_value == "ДД.ММ.ГГГГ":
                continue
            normalized = normalize_date_value(date_value)
            if not normalized:
                messagebox.showwarning(
                    "Проверка",
                    f"Неверная дата для пункта «{item_name}».",
                )
                return
            parsed_date = self.parent._parse_date(normalized)
            if parsed_date is None:
                messagebox.showwarning(
                    "Проверка",
                    f"Неверная дата для пункта «{item_name}».",
                )
                return
            notes = self.notes_var.get().strip()
            payloads.append(
                RecordInput(
                    person=person,
                    item=item_name,
                    category=category,
                    due_date=parsed_date.isoformat(),
                    notes=notes,
                )
            )
        if not payloads:
            messagebox.showwarning(
                "Проверка", "Заполните хотя бы одну дату для добавления."
            )
            return
        self.parent._insert_records(payloads)
        self.destroy()


class EditAllDialog(tk.Toplevel):
    def __init__(self, parent: EpidemiologistTracker, person: str) -> None:
        super().__init__(parent)
        self.title("Изменить записи")
        self.resizable(False, False)
        self.parent = parent
        self.person = person
        self.entries: dict[tuple[str, str], tk.StringVar] = {}

        self._build_form()
        self.grab_set()
        self.transient(parent)

    def _build_form(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Сотрудник / группа").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(frame, text=self.person).grid(row=1, column=0, sticky=tk.W)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=2, column=0, columnspan=3, pady=(12, 0), sticky=tk.W)

        ttk.Label(list_frame, text="Название").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(list_frame, text="Срок (ДД.ММ.ГГГГ)").grid(
            row=0, column=1, sticky=tk.W
        )

        cursor = self.parent.connection.execute(
            "SELECT item, due_date, notes FROM records WHERE person = ?",
            (self.person,),
        )
        latest_dates: dict[str, date] = {}
        note_text = "-"
        for item, due_date, notes in cursor.fetchall():
            parsed = date.fromisoformat(due_date)
            existing = latest_dates.get(item)
            if existing is None or parsed > existing:
                latest_dates[item] = parsed
            if notes and note_text == "-":
                note_text = notes

        for index, (category, item_name) in enumerate(MEDBOOK_ITEMS, start=1):
            ttk.Label(list_frame, text=item_name).grid(
                row=index, column=0, sticky=tk.W, pady=2
            )
            date_var = tk.StringVar()
            existing = latest_dates.get(item_name)
            if existing:
                date_var.set(existing.strftime("%d.%m.%Y"))
            date_entry = ttk.Entry(list_frame, textvariable=date_var, width=16)
            date_entry.grid(row=index, column=1, sticky=tk.W)
            attach_date_placeholder(date_entry, date_var, use_placeholder=False)
            self.entries[(category, item_name)] = date_var

        ttk.Label(frame, text="Примечание").grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        self.notes_var = tk.StringVar()
        if note_text != "-":
            self.notes_var.set(note_text)
        ttk.Entry(frame, textvariable=self.notes_var, width=50).grid(
            row=4, column=0, columnspan=3, sticky=tk.W
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=(12, 0), sticky=tk.E)
        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(button_frame, text="Сохранить", command=self._handle_submit).pack(
            side=tk.RIGHT
        )

    def _handle_submit(self) -> None:
        payloads: list[RecordInput] = []
        for category, item_name in MEDBOOK_ITEMS:
            date_value = self.entries[(category, item_name)].get().strip()
            if not date_value:
                continue
            normalized = normalize_date_value(date_value)
            if not normalized:
                messagebox.showwarning(
                    "Проверка",
                    f"Неверная дата для пункта «{item_name}».",
                )
                return
            parsed_date = self.parent._parse_date(normalized)
            if parsed_date is None:
                messagebox.showwarning(
                    "Проверка",
                    f"Неверная дата для пункта «{item_name}».",
                )
                return
            payloads.append(
                RecordInput(
                    person=self.person,
                    item=item_name,
                    category=category,
                    due_date=parsed_date.isoformat(),
                    notes=self.notes_var.get().strip(),
                )
            )
        if not payloads:
            messagebox.showwarning(
                "Проверка", "Заполните хотя бы одну дату для изменения."
            )
            return
        self.parent._insert_records(payloads)
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
