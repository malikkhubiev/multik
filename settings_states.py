from aiogram.fsm.state import State, StatesGroup

class SettingsStates(StatesGroup):
    waiting_for_project_name = State()
    waiting_for_token = State()
    waiting_for_business_file = State()
    # Новые состояния для управления проектами
    waiting_for_new_project_name = State()
    waiting_for_additional_data_file = State()
    waiting_for_new_data_file = State()
    waiting_for_delete_confirmation = State()
    waiting_for_feedback_rating = State()
    waiting_for_feedback_text = State()
    waiting_for_new_token = State()  # <--- новое состояние для смены токена 
    waiting_for_payment_check = State()
    
    # Состояния для работы с формами
    waiting_for_form_name = State()
    waiting_for_field_name = State()
    waiting_for_field_type = State()
    waiting_for_form_edit = State()

class ExtendedSettingsStates(StatesGroup):
    waiting_for_payment_confirmation = State() 