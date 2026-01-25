import sqlite3
import tkinter as tk
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

DB_PATH = "epidemiologist.db"
DUE_SOON_DAYS = 30


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
        self.geometry("980x540")
        self.minsize(900, 500)

        self.connection = sqlite3.connect(DB_PATH)
        self._init_db()

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

        ttk.Button(button_frame, text="Добавить", command=self._open_add_dialog).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Изменить", command=self._open_edit_dialog).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Удалить", command=self._delete_record).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Обновить", command=self._load_records).pack(
            side=tk.LEFT
        )

        legend = ttk.Label(
            button_frame,
            text="Легенда: красный — просрочено, жёлтый — скоро истекает",
        )
        legend.pack(side=tk.RIGHT)

        columns = ("person", "item", "category", "due_date", "status", "notes")
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            height=18,
        )
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        self.tree.heading("person", text="Сотрудник / группа")
        self.tree.heading("item", text="Название")
        self.tree.heading("category", text="Категория")
        self.tree.heading("due_date", text="Срок до")
        self.tree.heading("status", text="Статус")
        self.tree.heading("notes", text="Примечание")

        self.tree.column("person", width=160)
        self.tree.column("item", width=200)
        self.tree.column("category", width=140)
        self.tree.column("due_date", width=100, anchor=tk.CENTER)
        self.tree.column("status", width=140, anchor=tk.CENTER)
        self.tree.column("notes", width=220)

        self.tree.tag_configure("overdue", background="#f8d7da")
        self.tree.tag_configure("due_soon", background="#fff3cd")
        self.tree.tag_configure("ok", background="#e7f5ff")

    def _load_records(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        cursor = self.connection.execute(
            "SELECT id, person, item, category, due_date, notes FROM records"
        )
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
            self.tree.insert(
                "",
                tk.END,
                iid=str(record.record_id),
                values=(
                    record.person,
                    record.item,
                    record.category,
                    record.due_date.isoformat(),
                    status_label,
                    record.notes,
                ),
                tags=(tag,),
            )

    def _status_for(self, due_date: date) -> tuple[str, str]:
        today = date.today()
        if due_date < today:
            return "Просрочено", "overdue"
        if due_date <= today + timedelta(days=DUE_SOON_DAYS):
            return f"Скоро истекает ({DUE_SOON_DAYS} дн.)", "due_soon"
        return "В норме", "ok"

    def _open_add_dialog(self) -> None:
        RecordDialog(self, "Добавить запись", self._insert_record)

    def _open_edit_dialog(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Выбор записи", "Выберите запись для изменения.")
            return
        record_id = int(selection[0])
        cursor = self.connection.execute(
            "SELECT person, item, category, due_date, notes FROM records WHERE id = ?",
            (record_id,),
        )
        row = cursor.fetchone()
        if not row:
            messagebox.showerror("Ошибка", "Запись не найдена.")
            return
        RecordDialog(
            self,
            "Изменить запись",
            lambda payload: self._update_record(record_id, payload),
            initial=RecordInput(
                person=row[0],
                item=row[1],
                category=row[2],
                due_date=row[3],
                notes=row[4] or "",
            ),
        )

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
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Выбор записи", "Выберите запись для удаления.")
            return
        record_id = int(selection[0])
        if not messagebox.askyesno(
            "Подтверждение", "Удалить выбранную запись?"
        ):
            return
        with self.connection:
            self.connection.execute("DELETE FROM records WHERE id = ?", (record_id,))
        self._load_records()

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


class RecordDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        on_submit: callable,
        initial: RecordInput | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.on_submit = on_submit
        self.initial = initial or RecordInput("", "", "", "", "")

        self._build_form()
        self.grab_set()
        self.transient(parent)

    def _build_form(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        self.person_var = tk.StringVar(value=self.initial.person)
        self.item_var = tk.StringVar(value=self.initial.item)
        self.category_var = tk.StringVar(value=self.initial.category)
        self.date_var = tk.StringVar(value=self.initial.due_date)
        self.notes_var = tk.StringVar(value=self.initial.notes)

        self._add_field(frame, "Сотрудник / группа", self.person_var, 0)
        self._add_field(frame, "Название", self.item_var, 1)
        self._add_field(frame, "Категория", self.category_var, 2)
        self._add_field(frame, "Срок до (ГГГГ-ММ-ДД)", self.date_var, 3)

        notes_label = ttk.Label(frame, text="Примечание")
        notes_label.grid(row=4, column=0, sticky=tk.W, pady=(6, 0))
        notes_entry = ttk.Entry(frame, textvariable=self.notes_var, width=40)
        notes_entry.grid(row=5, column=0, columnspan=2, sticky=tk.W)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=6, column=0, columnspan=2, pady=(12, 0), sticky=tk.E)

        ttk.Button(button_frame, text="Отмена", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(button_frame, text="Сохранить", command=self._handle_submit).pack(
            side=tk.RIGHT
        )

    def _add_field(
        self, frame: ttk.Frame, label: str, variable: tk.StringVar, row: int
    ) -> None:
        ttk.Label(frame, text=label).grid(row=row * 2, column=0, sticky=tk.W)
        entry = ttk.Entry(frame, textvariable=variable, width=40)
        entry.grid(row=row * 2 + 1, column=0, columnspan=2, sticky=tk.W)

    def _handle_submit(self) -> None:
        payload = RecordInput(
            person=self.person_var.get().strip(),
            item=self.item_var.get().strip(),
            category=self.category_var.get().strip(),
            due_date=self.date_var.get().strip(),
            notes=self.notes_var.get().strip(),
        )
        missing_fields = []
        if not payload.person:
            missing_fields.append("сотрудник/группа")
        if not payload.item:
            missing_fields.append("название")
        if not payload.category:
            missing_fields.append("категория")
        if not payload.due_date:
            missing_fields.append("срок")
        if missing_fields:
            messagebox.showwarning(
                "Проверка",
                "Заполните поля: " + ", ".join(missing_fields) + ".",
            )
            return
        parsed_date = self._parse_date(payload.due_date)
        if parsed_date is None:
            messagebox.showwarning(
                "Проверка",
                "Введите дату в формате ГГГГ-ММ-ДД или ДД.ММ.ГГГГ.",
            )
            return
        if parsed_date.year < 2000 or parsed_date.year > 2100:
            messagebox.showwarning(
                "Проверка", "Проверьте год даты срока действия."
            )
            return
        self.on_submit(payload)
        self.destroy()

    @staticmethod
    def _parse_date(value: str) -> date | None:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None


if __name__ == "__main__":
    app = EpidemiologistTracker()
    app.mainloop()
