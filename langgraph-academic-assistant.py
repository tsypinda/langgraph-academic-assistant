import os
from dotenv import load_dotenv
import requests
from langchain_gigachat import GigaChat
from langchain_core.messages import SystemMessage, HumanMessage
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from datetime import datetime
import json
from langchain_core.tools import tool
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
import telebot

load_dotenv()
API_KEY = os.getenv("GIGACHAT_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_KEY or not BOT_TOKEN:
    raise ValueError("Критическая ошибка: Токены GIGACHAT_API_KEY или TELEGRAM_BOT_TOKEN не найдены в окружении!")
class State(TypedDict):
    messages: Annotated[list, add_messages]


@tool
def save_json(json_data: str) -> str:
    """
    Запись в JSON файл requests.json информации.
    Добавление информации в уже существующий requests.json.
    На вход получаем JSON строку для сохранения.
    На выход возвращаем сообещние об удачном завершении записи.
    Сохранение записи в файл.
    """
    try:
        entry = json.loads(json_data)
        try:
            with open('requests.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            data = []
        data.append(entry)

        with open('requests.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return f"Данные сохранены. Всего записей: {len(data)}"
    
    except:
        return "Ошибка записи!"

@tool
def sort_data(subject: str, start: str, end: str) -> str:
    """Возвращает список сохраненных материалов по предмету за указанный период
    Аргументы:
        subject: предмет для фильтрации
        start: начало периода в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС
        end: конец периода в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС
    """
    with open('requests.json', 'r', encoding='utf-8') as f: all_data = json.load(f)

    filtered = [item for item in all_data if item['subject'].lower() == subject.lower()]
    filtered = [item for item in filtered if item["date"] >= start]
    filtered = [item for item in filtered if item["date"] <= end]

    if not filtered:
        return f"Материалы по предмету '{subject}' за указанный период не найдены"

    # Возвращаем отформатированный JSON
    print(json.dumps(filtered, indent=2, ensure_ascii=False))

    return json.dumps(filtered, indent=2, ensure_ascii=False)

tools = [save_json, sort_data]

system_prompt = SystemMessage(content="""
            Ты - академический ассистент. Определи, к какой категории из перечисленных относится текст:
            1. Численные методы; 2. Компьютерные сети; 3. Программирование на Python; 4. Физика. Используй только эти категории, не придумывай своих. 
            В subject запрещено использовать альтернативные варианты, кроме перечисленных.
            Укажи дату отправки сообщения, а также ссылку на 
            сайт, с которого будет заружена информация. Если страницу не удалось
            загрузить (на вход получишь "Ошибка загрузки"), отвечай, что не удалось загрузить страницу.
            Отвечай кратко, только категорией из четырех перечисленных, не должно быть иных категорий. Называй категорию по её названию.
        """)
        
save_prompt = SystemMessage(content="""
            Если тебя просят вызвать функцию save_text, твоей задачей будет именно вызвать ее. Сообщи пользователю,
            удалось ли это сделать - вызвать функцию. Отвечай кратко.
        """)

chat_prompt = SystemMessage(content="""
    Ты - дружелюбный академический ассистент. Ты помогаешь студентам.
    Если пользователь просит показать материалы (например, "материалы по физике за 2026-01-01 2026-02-01"), 
    вызови инструмент sort_data. В качестве аргументов используй название предмета (subject - Численные методы, Компьютерные сети,Программирование на Python, Физика),
    время, от которого нужно брать отсчет в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС (start - если указано) и аналогично время, до которого нужно
    брать запросы .
    В остальных случаях просто общайся и отвечай на вопросы.
    """)

graph_builder = StateGraph(State)
tool_node = ToolNode(tools = tools)

llm = GigaChat(credentials=API_KEY, verify_ssl_certs=False, model="GigaChat-2")
llm = llm.bind_tools(tools)
llm_chat = GigaChat(credentials=API_KEY, verify_ssl_certs=False, model="GigaChat-2").bind_tools(tools)

def chatbot(state: State):
    return {"messages": [llm.invoke([system_prompt] + state["messages"])]}

graph_builder.add_node("tools", tool_node)
graph_builder.add_node("chatbot", chatbot)
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")
graph = graph_builder.compile()

def stream_graph_updates(user_input: str):
    for event in graph.stream({"messages": [HumanMessage(content=user_input)]}):
        for value in event.values():
            print("ИИ-агент:", value["messages"][-1].content)



class Response(BaseModel):

    """Информация о времени отправки сообщения, имени пользлвателя и сайт"""

    date: str = Field(description="Время отправки сообщения")
    subject: str = Field(description="Название предмета без пояснений")
    url: str = Field(description="Оригинальная ссылка")

llm_structured = GigaChat(credentials=API_KEY, verify_ssl_certs=False, model="GigaChat-2").with_structured_output(Response)

def get_text(url):
    try: 
        response = requests.get(url, timeout=10) 
        response.raise_for_status() 

        soup = BeautifulSoup(response.text, 'html.parser')

        for script_or_style in soup(["script", "style"]): 
            script_or_style.decompose() 
            
        return soup.get_text(separator=" ", strip=True)[:1000]

    except:
        return "Ошибка загрузки"

bot = telebot.TeleBot(BOT_TOKEN)
@bot.message_handler(content_types=['text'])

def handle_message(message):
    user_input = message.text
    chat_id = message.from_user.id
    
    if user_input == "exit":
        bot.send_message(chat_id, "Пока!")
        return
        
    if user_input.startswith(('http://', 'https://')):
        current_datetime = datetime.now()

        structured_prompt = f"""
        время отправки сообщения {current_datetime}, оригинальную ссылка {user_input}.
        Отнеси к одному предмету из перечисленных. Текст: {get_text(user_input)}
        """

        structured_messages = [system_prompt, structured_prompt]
        structured_response = llm_structured.invoke(structured_messages)
        result = structured_response.model_dump_json()

        bot.send_message(chat_id, result)

        tool_prompt = HumanMessage(content=f"""
            Вызови функцию save_json с параметром json_data, равным этой строке: {result}
            
            Важно: функция save_json принимает ровно один аргумент - json_data.
            Передай в него указанную выше JSON строку.
            """)
        tool_messages = [save_prompt, tool_prompt]
        tool_response = llm.invoke(tool_messages)
        result = save_json.invoke(tool_response.tool_calls[0])
        bot.send_message(chat_id, result.content)

    else:
        messages = [chat_prompt, HumanMessage(content=user_input)]
        response = llm_chat.invoke(messages)
        try:
            if response.tool_calls[-1]['name'] == 'sort_data':
                args = response.tool_calls[-1]['args']
                tool_result = sort_data.invoke(args)
                bot.send_message(chat_id, tool_result)
        except: 
            bot.send_message(chat_id, response.content)

if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(none_stop=True, interval=0)

        
