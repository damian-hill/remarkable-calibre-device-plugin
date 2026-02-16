"""Custom configuration widget for the reMarkable Calibre plugin.

Provides radio buttons for device model and preferred format,
plus per-model PDF conversion presets (margin, font size, font).
"""
from __future__ import annotations

try:
    from qt.core import (QButtonGroup, QCheckBox, QFormLayout, QGroupBox,
                          QHBoxLayout, QLabel, QLineEdit, QPushButton,
                          QRadioButton, QSpinBox, QVBoxLayout, QWidget)
except ImportError:
    from PyQt5.Qt import (QButtonGroup, QCheckBox, QFormLayout, QGroupBox,
                           QHBoxLayout, QLabel, QLineEdit, QPushButton,
                           QRadioButton, QSpinBox, QVBoxLayout, QWidget)

# Model presets — mirrors DEVICE_PDF_SETTINGS in __init__.py
MODEL_PRESETS = {
    "rm2":       {"margin": 36, "font_size": 18},
    "paper-pro": {"margin": 36, "font_size": 20},
    "pro-move":  {"margin": 18, "font_size": 14},
}


class RemarkableConfigWidget(QWidget):
    """Settings panel with radio buttons for model and format."""

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

        extra = plugin.settings().extra_customization or []
        defaults = plugin.EXTRA_CUSTOMIZATION_DEFAULT

        def _get(i, fallback):
            return extra[i] if i < len(extra) and extra[i] is not None else fallback

        layout = QVBoxLayout(self)

        # -- Connection --
        conn = QGroupBox("Connection")
        conn_form = QFormLayout()

        self.ip_edit = QLineEdit(_get(0, defaults[0]))
        self.ip_edit.setPlaceholderText("10.11.99.1")
        self.ip_edit.setToolTip(
            "Connect your reMarkable via USB, then enable\n"
            "Settings > Storage to start the USB web interface."
        )
        conn_form.addRow("IP address:", self.ip_edit)

        conn.setLayout(conn_form)
        layout.addWidget(conn)

        # -- Device Model (radio buttons) --
        model_group = QGroupBox("Device model")
        model_layout = QVBoxLayout()
        self._model_buttons = QButtonGroup(self)

        models = [
            ("rm2", "reMarkable 1 / 2  (6.2\u2033 \u00d7 8.3\u2033)"),
            ("paper-pro", "Paper Pro  (7.1\u2033 \u00d7 9.4\u2033)"),
            ("pro-move", "Paper Pro Move  (3.6\u2033 \u00d7 6.4\u2033)"),
        ]
        current_model = _get(1, defaults[1])
        for i, (value, label) in enumerate(models):
            rb = QRadioButton(label)
            rb.setProperty("model_value", value)
            if value == current_model:
                rb.setChecked(True)
            self._model_buttons.addButton(rb, i)
            model_layout.addWidget(rb)

        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # -- Preferred Format (radio buttons) --
        fmt_group = QGroupBox("Preferred format")
        fmt_layout = QVBoxLayout()
        self._format_buttons = QButtonGroup(self)

        formats = [
            ("pdf", "PDF \u2014 converts EPUBs for your screen (recommended)"),
            ("epub", "EPUB \u2014 send as-is"),
        ]
        current_fmt = _get(2, defaults[2])
        for i, (value, label) in enumerate(formats):
            rb = QRadioButton(label)
            rb.setProperty("format_value", value)
            if value == current_fmt:
                rb.setChecked(True)
            self._format_buttons.addButton(rb, i)
            fmt_layout.addWidget(rb)

        fmt_group.setLayout(fmt_layout)
        layout.addWidget(fmt_group)

        # -- PDF Conversion Settings --
        pdf_group = QGroupBox("PDF conversion settings")
        pdf_form = QFormLayout()

        # Margin (all four sides, in points)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 144)
        self.margin_spin.setSuffix(" pt")
        self.margin_spin.setToolTip(
            "Page margin in points (all four sides).\n"
            "Set to 0 to use the model default."
        )
        saved_margin = int(_get(5, defaults[5]) or 0)
        if saved_margin:
            self.margin_spin.setValue(saved_margin)
        else:
            self.margin_spin.setValue(MODEL_PRESETS.get(current_model, MODEL_PRESETS["paper-pro"])["margin"])
        pdf_form.addRow("Margin:", self.margin_spin)

        # Font size (in points)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 48)
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.setToolTip(
            "Default font size in points.\n"
            "Set to 0 to use the model default."
        )
        saved_font_size = int(_get(6, defaults[6]) or 0)
        if saved_font_size:
            self.font_size_spin.setValue(saved_font_size)
        else:
            self.font_size_spin.setValue(MODEL_PRESETS.get(current_model, MODEL_PRESETS["paper-pro"])["font_size"])
        pdf_form.addRow("Font size:", self.font_size_spin)

        # Font family
        self.font_edit = QLineEdit(str(_get(7, defaults[7]) or ""))
        self.font_edit.setPlaceholderText("System default (serif)")
        self.font_edit.setToolTip(
            "Serif font family for body text.\n"
            "Examples: Georgia, Bookerly, Literata, Palatino\n"
            "Leave empty for the system default."
        )
        pdf_form.addRow("Font:", self.font_edit)

        # Preset label + reset button
        preset_row = QHBoxLayout()
        self._preset_label = QLabel()
        self._update_preset_label(current_model)
        preset_row.addWidget(self._preset_label)
        preset_row.addStretch()
        reset_btn = QPushButton("Reset to model defaults")
        reset_btn.setToolTip("Reset margin and font size to the selected model's recommended values.")
        reset_btn.clicked.connect(self._reset_to_presets)
        preset_row.addWidget(reset_btn)
        pdf_form.addRow("", preset_row)

        self.embed_fonts_check = QCheckBox("Embed all fonts (slower, higher fidelity)")
        self.embed_fonts_check.setChecked(bool(_get(8, defaults[8]) if len(defaults) > 8 else True))
        self.embed_fonts_check.setToolTip(
            "When enabled, all fonts are embedded in the PDF.\n"
            "Disable for faster conversion — the reMarkable will\n"
            "use its own fonts for any non-embedded fonts."
        )
        pdf_form.addRow("", self.embed_fonts_check)

        pdf_group.setLayout(pdf_form)
        layout.addWidget(pdf_group)

        # Connect model change to update preset label
        self._model_buttons.buttonClicked.connect(self._on_model_changed)

        # -- Upload Options --
        upload = QGroupBox("Upload options")
        upload_form = QFormLayout()

        self.folder_edit = QLineEdit(_get(3, defaults[3]))
        self.folder_edit.setPlaceholderText("Leave empty for root")
        self.folder_edit.setToolTip("Name of a folder on your reMarkable to upload into.")
        upload_form.addRow("Target folder:", self.folder_edit)

        self.cover_check = QCheckBox("Inject cover page when EPUB is missing one")
        self.cover_check.setChecked(bool(_get(4, defaults[4])))
        upload_form.addRow("", self.cover_check)

        upload.setLayout(upload_form)
        layout.addWidget(upload)

        layout.addStretch()

    def _selected_model(self) -> str:
        btn = self._model_buttons.checkedButton()
        return btn.property("model_value") if btn else "paper-pro"

    def _selected_format(self) -> str:
        btn = self._format_buttons.checkedButton()
        return btn.property("format_value") if btn else "pdf"

    def _update_preset_label(self, model: str):
        preset = MODEL_PRESETS.get(model, MODEL_PRESETS["paper-pro"])
        self._preset_label.setText(
            f"Model defaults: {preset['margin']} pt margin, {preset['font_size']} pt font"
        )

    def _on_model_changed(self, button):
        model = button.property("model_value")
        self._update_preset_label(model)
        preset = MODEL_PRESETS.get(model, MODEL_PRESETS["paper-pro"])
        self.margin_spin.setValue(preset["margin"])
        self.font_size_spin.setValue(preset["font_size"])
        self.font_edit.clear()

    def _reset_to_presets(self):
        model = self._selected_model()
        preset = MODEL_PRESETS.get(model, MODEL_PRESETS["paper-pro"])
        self.margin_spin.setValue(preset["margin"])
        self.font_size_spin.setValue(preset["font_size"])
        self.font_edit.clear()

    def validate(self):
        return True

    def commit(self) -> list:
        """Return settings as a list for extra_customization storage."""
        return [
            self.ip_edit.text().strip(),
            self._selected_model(),
            self._selected_format(),
            self.folder_edit.text().strip(),
            self.cover_check.isChecked(),
            self.margin_spin.value(),
            self.font_size_spin.value(),
            self.font_edit.text().strip(),
            self.embed_fonts_check.isChecked(),
        ]
