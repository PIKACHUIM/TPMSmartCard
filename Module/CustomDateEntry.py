from tkcalendar import DateEntry
import tkinter as tk
root = tk.Tk()

class CustomDateEntry(DateEntry):

    def _select(self, event=None):
        date = self._calendar.selection_get()
        if date is not None:
            self._set_text(date.strftime('%m/%d/%Y'))
            self.event_generate('<<DateEntrySelected>>')
        self._top_cal.withdraw()
        if 'readonly' not in self.state():
            self.focus_set()



entry = CustomDateEntry(root)
entry._set_text(entry._date.strftime('%m/%d/%Y'))
entry.pack()

root.mainloop()