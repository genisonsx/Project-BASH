import logging
import random
import requests
import settings

from datetime import datetime
from bson.objectid import ObjectId
from pymongo import MongoClient
from threading import Thread

import telebot
from telebot.types import (
    BotCommand,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputMediaPhoto,
    InputTextMessageContent
)

from telegraph import Telegraph



# Configuração do cliente MongoDB
client = MongoClient(settings.MONGO_URL)
USERS_DB = client.playgobot.users
MOVIES_DB = client.playgobot.movies

# Configuração do TeleBot
bot = telebot.TeleBot(token=settings.BOT_TOKEN, parse_mode="HTML")
bot.set_my_commands(commands=[BotCommand("start", "Iniciar bot.")])


def is_admin(user_id) -> bool:
    return USERS_DB.find_one({"_id": int(user_id), "permission": 1}) is not None

def check_user_blocked(user_id) -> bool:
    return USERS_DB.find_one({"_id": int(user_id), "blocked": True}) is not None

# Obtendo informações do filme
def get_movie_info_tmdb(tmdb_id: int):
    try:
        movie_response = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}",
            headers={
                "accept": "application/json",
                "Authorization": settings.TMDB_AUTHORIZATION
            },
            params={
                "language": "pt-BR",
                "append_to_response": "release_dates"
            }
        )
        movie_response.raise_for_status()

        if movie_response.status_code == 404:
            return None

        movie_data = movie_response.json()

        age_rating = next(
            (result["release_dates"][0]["certification"].replace("L", "Livre")
             for result in movie_data.get("release_dates", {}).get("results", [])
             if result["iso_3166_1"] == "BR" and result["release_dates"]), 
            ""
        )

        credits_response = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits",
            headers={
                "accept": "application/json",
                "Authorization": settings.TMDB_AUTHORIZATION
            },
            params={"language": "pt-BR"}
        )
        credits_response.raise_for_status()

        credits_data = credits_response.json()
        actors = sorted(cast["name"] for cast in credits_data.get("cast", [])[:5])
        director = sorted(crew["name"] for crew in credits_data.get("crew", []) if crew["job"] == "Director")
        
        telegraph = Telegraph()
        telegraph.create_account(short_name="@PlayGoNews")

        telegraph_url = telegraph.create_page(
            movie_data["title"],
            html_content=f"<p>{movie_data['overview']}</p>",
            author_name="@PlayGoNews"
        ).get("url")

        return {
            "tmdb_id": tmdb_id,
            "title": movie_data.get("title", ""),
            "original_title": movie_data.get("original_title", ""),
            "tagline": movie_data.get("tagline", ""),
            "release_date": movie_data.get("release_date", ""),
            "poster_url": f"https://image.tmdb.org/t/p/w500{movie_data.get('poster_path', '')}",
            "backdrop_url": f"https://image.tmdb.org/t/p/w1280{movie_data.get('backdrop_path', '')}",
            "overview": movie_data.get("overview", ""),
            "age_rating": age_rating,
            "genres": sorted(genre["name"] for genre in movie_data.get("genres", [])),
            "telegraph_url": telegraph_url,
            "actors": actors,
            "director": director,
        }
    except Exception as ex:
        logging.error(ex)
        return None

# Definindo informações do filme
def set_info_movie(user_id, movie_id):
    try:
        movie = MOVIES_DB.find_one({"_id": int(movie_id)})
        if movie:
            genres = ", ".join(movie["genres"])
            director = ", ".join(movie["director"])
            overview = movie["overview"][:100] + f"... <a href='{movie['telegraph_url']}'>Ler mais</a>" if len(movie["overview"]) > 100 else movie["overview"]
            photo = random.choice([movie["poster_url"], movie["backdrop_url"]]) or "https://telegra.ph/file/80511af9c62004cf3d182.jpg"

            bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=f"<b>Título:</b> {movie['title']}\n<b>Ano de Lançamento:</b> {movie['release_date'][:4]}\n<b>Classificação indicativa:</b> {movie['age_rating'] or 'Sem informações'}\n<b>Direção:</b> {director}\n<b>Gêneros:</b> {genres}\n\n<b>Sinopse:</b> {overview}",
                reply_markup=submit_movie_info_markup(movie)
            )
    except Exception as ex:
        logging.error(ex)

# Consulta de retorno de chamadas
@bot.callback_query_handler(func=lambda call: True)
def callback_query_handler(call):
	if check_user_blocked(call.from_user.id):
	   return
	   
	if call.data == "start":
		count_movies = MOVIES_DB.count_documents({"active": True})

		bot.edit_message_media(
    		media=InputMediaPhoto(
    		media="https://telegra.ph/file/eac45b43d3a286f4c2d24.jpg",  
    		caption=f"<b>👋 Bem-vindo(a),</b> <i>{call.from_user.first_name.title()}.</i>\n\n💡 Clique no botão <b>🔍 Pesquisar</b> para encontrar o filme que deseja assistir.\n\n📢 @PlayGoNews\n<b>🔢 Catálogo atual:</b> <i>{count_movies} filmes.</i>",
            parse_mode="HTML"
    	), 
    		chat_id=call.from_user.id, 
    		message_id=call.message.message_id,
    		reply_markup=start_markup()
    	)
    
	elif call.data.startswith("show_movie:"):
	    movie_id = int(call.data.split(":")[1])
	    movie = MOVIES_DB.find_one({"_id": movie_id})
    	
	    genres = ", ".join(movie["genres"])
	    overview = movie["overview"][:100] + f"... <a href='{movie['telegraph_url']}'>Ler mais</a>" if len(movie["overview"]) > 100 else movie["overview"]
	    photo = random.choice([movie["poster_url"] or "https://telegra.ph/file/80511af9c62004cf3d182.jpg", movie["backdrop_url"] or "https://telegra.ph/file/80511af9c62004cf3d182.jpg"])
	    director = ", ".join(movie["director"])
    	
	    bot.edit_message_media(
    		media=InputMediaPhoto(
    		media=photo,  
    		caption=f"<b>Título:</b> {movie['title']}\n<b>Ano de Lançamento:</b> {movie['release_date'][:4]}\n<b>Classificação indicativa:</b> {movie['age_rating'] or 'Sem informações'}\n<b>Direção:</b> {director}\n<b>Gêneros:</b> {genres}\n\n<b>Sinopse:</b> {overview}",
            parse_mode="HTML"
    	), 
    		chat_id=call.from_user.id, 
    		message_id=call.message.message_id,
    		reply_markup=submit_movie_info_markup(movie)
    	)

	elif call.data.startswith("show_movie_video:"):
		try:
		    query_data = call.data.split(":")
		    movie_id = int(query_data[1])
		    video_type = query_data[2]
	    	
		    movie = MOVIES_DB.find_one({"_id": movie_id}, {
		        "title": 1,
		        "release_date": 1,
		        "actors": 1,
		        "videos.dublado_msg_id": 1,
		        "videos.legendado_msg_id": 1,
		        "videos.nacional_msg_id": 1
	    	})
	    	
		    if movie:
		       dubbed_msg_id = movie["videos"].get("dublado_msg_id")
		       subtitled_msg_id = movie["videos"].get("legendado_msg_id")
		       national_msg_id = movie["videos"].get("nacional_msg_id")
		       
		       msg_id = None
		       if video_type == "dublado" and dubbed_msg_id:
		       	msg_id = dubbed_msg_id
		       elif video_type == "legendado" and subtitled_msg_id:
		       	msg_id = subtitled_msg_id
		       elif video_type == "nacional" and national_msg_id:
		       	msg_id = national_msg_id
		       else:
		       	if dubbed_msg_id:
		       		msg_id = dubbed_msg_id
		       		video_type = "dublado"
		       	elif subtitled_msg_id:
		       		msg_id = subtitled_msg_id
		       		video_type = "legendado"
		       	elif national_msg_id:
		       		msg_id = national_msg_id
		       		video_type = "nacional"
	    	   		
		       if not msg_id:
		       	bot.reply_to(call.message, "Não foi possível encontrar um arquivo de vídeo disponível.")
	    	   	return

		    buttons = []
		    if dubbed_msg_id:
		    	buttons.append([InlineKeyboardButton(
	    			f"{'✅' if video_type == 'dublado' else ''} Dublado", 
	    			callback_data="noop" if video_type == "dublado" else f"show_movie_video:{movie_id}:dublado"
	    		)])
		    if subtitled_msg_id:
		    	buttons.append([InlineKeyboardButton(
	    			f"{'✅' if video_type == 'legendado' else ''} Legendado", 
	    			callback_data="noop" if video_type == "legendado" else f"show_movie_video:{movie_id}:legendado"
	    		)])
		    if national_msg_id:
		    	buttons.append([InlineKeyboardButton(
	    			f"{'✅' if video_type == 'nacional' else ''} Nacional", 
	    			callback_data="noop" if video_type == "nacional" else f"show_movie_video:{movie_id}:nacional"
	    		)])
		    buttons.append([
	    		InlineKeyboardButton("↖ Voltar", callback_data=f"show_movie:{movie_id}"), 
	    		InlineKeyboardButton("🔆 Início", callback_data="start")
	    	])
		    markup = InlineKeyboardMarkup(buttons)
	    	
		    actors = ", ".join(movie["actors"])
		    bot.copy_message(
                chat_id=call.from_user.id,
                message_id=msg_id,
                from_chat_id=settings.CHANNEL_BACKUP,
                caption=f"• <b>{movie['title']}</b> ({movie['release_date'][:4]})\n<b>Atores:</b> <i>{actors}</i>",
                reply_markup=markup
            )
		    bot.delete_message(chat_id=call.from_user.id, message_id=call.message.message_id)
		except:
			bot.answer_callback_query(call.id, text="Algo deu errado! 🚨", show_alert=True)

# Start
def start_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton(text="🔍 Pesquisar", switch_inline_query_current_chat="")
    )

@bot.message_handler(commands=["start"])
def start_command(message):
	if check_user_blocked(message.from_user.id):
		return
		
	try:
		user = USERS_DB.find_one({"_id": int(message.from_user.id)})
		if not user:
			USER = {
		        "_id": int(message.from_user.id),
		        "name": message.from_user.first_name,
		        "token": str(ObjectId()),
		        "blocked": False,
		        "permission": 0,
		        "registration_date": datetime.now()
		    }
			USERS_DB.insert_one(USER)

		if message.text == "/start":
			count_movies = MOVIES_DB.count_documents({"active": True})

			bot.send_photo(
				chat_id=message.from_user.id,
				photo="https://telegra.ph/file/eac45b43d3a286f4c2d24.jpg",
				caption=f"<b>👋 Bem-vindo(a),</b> <i>{message.from_user.first_name.title()}.</i>\n\n💡 Clique no botão <b>🔍 Pesquisar</b> para encontrar o filme que deseja assistir.\n\n📢 @PlayGoNews\n<b>🔢 Catálogo atual:</b> <i>{count_movies} filmes</i>.",
				reply_markup=start_markup()
			)
		else:
			set_info_movie(
				user_id=message.from_user.id,
				movie_id=message.text.split()[1]
			)
	except Exception as ex:
		logging.error(ex)

# Adicionar filme 
@bot.message_handler(commands=["f"])
def add_movie_command(message):
    if not is_admin(message.from_user.id):
        return

    try:
        args = message.text.split()[1:]
        if len(args) < 2:
            bot.reply_to(message, "Por favor, forneça o TMDb e os IDs das mensagens (dublado, legendado, e/ou nacional).")
            return
        
        tmdb_id = args[0]
        video_ids = {arg[0].lower(): int(arg[1:]) for arg in args[1:] if arg[0].lower() in "dln"}
        
        movie_info = get_movie_info_tmdb(int(tmdb_id))
        if movie_info is None:
            bot.reply_to(message, "Erro ao obter informações do filme do TMDb.")
            return
        
        movie_data = {
            "_id": int(tmdb_id),
            "title": movie_info["title"],
            "original_title": movie_info["original_title"],
            "tagline": movie_info["tagline"],
            "release_date": movie_info["release_date"],
            "poster_url": movie_info["poster_url"],
            "backdrop_url": movie_info["backdrop_url"],
            "overview": movie_info["overview"],
            "age_rating": movie_info["age_rating"],
            "telegraph_url": movie_info["telegraph_url"],
            "genres": movie_info["genres"],
            "actors": movie_info["actors"],
            "director": movie_info["director"],
            "videos": {
                "dublado_msg_id": video_ids.get("d"),
                "legendado_msg_id": video_ids.get("l"),
                "nacional_msg_id": video_ids.get("n")
            },
            "status": {
                "token": str(ObjectId()),
                "creator_id": int(message.from_user.id),
                "registration_date": datetime.now(),
                "modification_date": datetime.now()
            },
            "active": True
        }
        result = MOVIES_DB.insert_one(movie_data)

        bot.reply_to(
            message, 
            text=f"Filme <a href='t.me/PlayGoBRBot?start={tmdb_id}'><b>{movie_info['title']}</b></a> adicionado com sucesso."
        )
        
        genres = ", ".join(movie_info["genres"])
        overview = movie_info["overview"][:1000] + f"... <a href='{movie_info['telegraph_url']}'>Ler mais</a>" if len(movie_info["overview"]) > 1000 else movie_info["overview"]
        
        bot.send_photo(
        	chat_id=settings.CHANNEL_POST,
        	photo=movie_info["poster_url"],
        	caption=f"<b>Título:</b> {movie_info['title']}\n<b>Ano de Lançamento:</b> {movie_info['release_date'][:4]}\n<b>Classificação indicativa:</b> {movie_info.get('age_rating', 'Sem informações')}\n<b>Gêneros:</b> {genres}\n\n<b>Sinopse:</b> {overview}",
        	reply_markup=InlineKeyboardMarkup().add(
	        	InlineKeyboardButton(text="🔗 Abrir", url=f"t.me/PlayGoBRBot?start={tmdb_id}")
	        )
        )
    except Exception as ex:
        logging.error(ex)

# Enviar informações do filme
def submit_movie_info_markup(movie) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton(text="🧲 IMDb", url=f"https://www.themoviedb.org/movie/{movie['_id']}?language=pt-BR"),
        InlineKeyboardButton(text="🔆 Início", callback_data="start"),
        InlineKeyboardButton(text="📺 Trailers", url=f"https://youtube.com/results?search_query=intitle:+trailer+{movie['title']}+{movie['release_date'][:4]}+|+dublado+legendado")
    )
    
    markup.add(InlineKeyboardButton(text="👁️ Assistir", callback_data=f"show_movie_video:{movie['_id']}:"))
    return markup

@bot.message_handler(func=lambda message: any(entity.type == "text_link" for entity in message.entities))
def submit_movie_info_func(message):
    if check_user_blocked(message.from_user.id):
        return
    
    try:
        for entity in message.entities:
            if entity.type == "text_link":
                movie_id = entity.url.split("/")[-2].replace(".filme", "")
                
                if movie_id.isdigit():
                    set_info_movie(
                    	user_id=message.from_user.id,
                        movie_id=int(movie_id)
                    )
    except Exception as ex:
        logging.error(ex)

# Pesquisa por filmes.
@bot.inline_handler(func=lambda _: True)
def search_movies(query, next_offset=None, results=[], limit_per_page=50):
    if check_user_blocked(query.from_user.id):
        return
    
    try:
        offset = int(query.offset) if query.offset else 0
        query_text = query.query.strip()
        
        if not query_text:
            return

        movies = list(
            MOVIES_DB.find({
                "active": True,
                "$or": [
                    {"title": {"$regex": query_text, "$options": "i"}},
                    {"original_title": {"$regex": query_text, "$options": "i"}}
                ]
            }).sort("title", 1).skip(offset).limit(limit_per_page)
        )
    
        if movies:
            results = [
                InlineQueryResultArticle(
                    id=movie["_id"],
                    title=movie["title"],
                    description=f"Filme dirigido por {', '.join(movie.get('director', []))} ({movie['release_date'][:4]})\n{movie.get('overview', '')}",
                    thumbnail_url=movie["poster_url"],
                    input_message_content=InputTextMessageContent(
                        message_text=f"<a href='http://{movie['_id']}.filme/'>#assistir</a>",
                        parse_mode="HTML"
                    )
                )
                for movie in movies
            ]
            next_offset = str(offset + len(movies)) if len(movies) == limit_per_page else None
            
        if not movies and offset == 0:
            results = [
                InlineQueryResultArticle(
                    id="no_results",
                    title="Nenhum resultado encontrado!",
                    description="Não encontramos nenhum filme com esse título.",
                    thumbnail_url="https://telegra.ph/file/b8b73bc3829ab86c8b957.jpg",
                    input_message_content=InputTextMessageContent(
                        message_text="Não encontramos nenhum filme com esse título."
                    )
                )
            ]
            next_offset = None
        
        bot.answer_inline_query(
            inline_query_id=query.id,
            results=results,
            next_offset=next_offset,
            cache_time=160,
            is_personal=True
        )
    except Exception as ex:
        logging.error(ex)



if __name__ == "__main__":
    	# Rodando bot
    th_bot = Thread(target=bot.infinity_polling())
    th_bot.start()