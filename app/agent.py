from datetime import datetime  # the current date and time

from google.genai import types  # settings objects for the chat call

from app.answer import CHAT_MODEL  # the chat model name we already chose
from app.booking import IST  # India time zone
from app.faq import _client  # the shared Google connection
from app.tools import Session, make_tools  # the call state and the toolbox

GREETING = "Hello, thank you for calling Kathara salon. This is Cheppandi. How can I help you today?"  # the first thing the caller hears


def build_rules(now):  # the written instruction sheet, with today's date filled in
    return (
        "You are Cheppandi, the voice receptionist at Kathara, a hair salon. "
        "The caller has already heard your greeting, so never greet again.\n"
        f"Today is {now.strftime('%A, %d %B %Y')} and the time is {now.strftime('%H:%M')} India time. "
        "Work out words like tomorrow or Saturday from this date, and give tools the day as YYYY-MM-DD and the time as HH:MM in 24 hour form.\n"
        "STYLE: speak like a friendly person on the phone. Use one or two short sentences, ask one question at a time, "
        "and never use lists, emojis or special symbols. Say times naturally, for example half past five in the evening.\n"
        "NEVER ask or guess the caller's gender. For a haircut, ask whether it is a men's cut or a women's cut, because the salon prices them separately.\n"
        "FLOW for a booking: find out the service, then ask which stylist the caller prefers or offer the first available one "
        "(never choose a stylist for them), then the day and time, then the caller's name and phone number.\n"
        "Call get_menu to learn services, durations and prices. Prices depend on the stylist level, so never quote a price you did not get from a tool. "
        "If a tool says a stylist level does not offer a service, offer a stylist at a level that does.\n"
        "Call find_free_slots before suggesting times, and suggest at most three. If the time is taken, offer the nearest free ones.\n"
        "Every booking must offer a manicure or pedicure once, by asking whether the caller would like to add one. "
        "Then ask once whether they would like any other services. Only if they say yes, mention: eyebrow threading, de tan, waxing, massage, bridal grooming and nail enhancements.\n"
        "Read the phone number back digit by digit and ask the caller to confirm it. "
        "Then call propose_booking, which checks everything and saves nothing. "
        "Read the returned summary back to the caller: services, stylist, day, time and the total price including any add ons, and ask for a clear yes. "
        "If the caller adds or changes anything, call propose_booking again with the new details.\n"
        "Call confirm_booking only after the caller has replied with a clear yes to that read back. "
        "Say the visit is booked ONLY if confirm_booking returns status confirmed. "
        "If any tool returns an error, explain it simply and offer an alternative. "
        "If confirm_booking says the caller has not replied yet, read the booking back and wait for their answer.\n"
        "For questions about hours, booking, cancellation, late arrival, payment or colour treatments, call answer_policy_question and use its answer. "
        "If it says grounded is false, say you are not sure and never invent a policy.\n"
        "If the caller wants to cancel a booking made in this conversation, use cancel_appointment with that booking id. "
        "If nothing has been booked yet, say there is nothing to cancel.\n"
        "Stay on salon topics. Politely decline anything else."
    )


def new_chat():  # starts one conversation, with its own toolbox and its own memory of what was said
    now = datetime.now(IST)  # the current time in India
    session = Session()  # the state of this call
    tools = make_tools(session)  # a toolbox tied to this call
    config = types.GenerateContentConfig(  # the settings for every reply in this chat
        system_instruction=build_rules(now),  # the instruction sheet
        tools=list(tools.values()),  # the tools the model may ask for
        temperature=0.2,  # low, so the behaviour stays steady
    )
    chat = _client().chats.create(model=CHAT_MODEL, config=config)  # a chat that remembers the history
    return chat, session  # the loop needs both


def main():  # a typed conversation, standing in for the phone call
    chat, session = new_chat()  # start a fresh conversation
    print(f"\nCheppandi: {GREETING}\n(type quit to stop)\n")  # the greeting, then instructions
    while True:  # keep going until the caller quits
        try:  # Ctrl+C or Ctrl+Z at the prompt should end the call cleanly
            text = input("You: ").strip()  # what the caller says
        except (EOFError, KeyboardInterrupt):  # the caller hung up
            print("\n(call ended)")  # a clean ending instead of a traceback
            break  # leave the loop
        if text.lower() in {"quit", "exit"}:  # the caller hangs up politely
            break  # leave the loop
        if not text:  # nothing typed
            continue  # ask again
        session.turn += 1  # count this message, confirm_booking uses this to enforce a separate reply
        try:  # the Google call can fail, for example when rate limited
            response = chat.send_message(text)  # the model replies, calling tools if it needs them
            reply = (response.text or "").strip()  # the spoken reply, or empty
        except Exception as exc:  # any failure lands here
            reply = f"(error: {type(exc).__name__}: {str(exc)[:150]})"  # short and visible, no key
        print(f"\nCheppandi: {reply or '(no reply)'}\n")  # what the caller would hear


if __name__ == "__main__":  # runs only when we start this file directly
    main()