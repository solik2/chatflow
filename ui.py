# Basic sample GUI for ChatFlow
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

w = ttk.Window(themename="superhero")
button_send = ttk.Button(w, text="Send", bootstyle="success")
button_send.pack(side=LEFT, padx=5, pady=10)
button_attach = ttk.Button(w, text="Attach", bootstyle="info-outline")
button_attach.pack(side=LEFT, padx=5, pady=10)

w.mainloop()
