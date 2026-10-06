import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow

if __name__ == "__main__":
    # Garante escalonamento preciso em monitores com DPI fracionário (125%, 150%…).
    # Em Qt 6 o High-DPI scaling já está ativo por padrão; esta política evita
    # o arredondamento que causaria borrão ou tamanhos incorretos de UI.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

    