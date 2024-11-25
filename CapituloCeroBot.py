from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from pymongo import MongoClient
from datetime import datetime
import requests

class CapituloCeroBot:
    def __init__(self, token):
        try: 
            self.client = MongoClient('mongodb://localhost:27017/')
            self.db = self.client.biblioteca_db
            self.token = token   
            
        except Exception as e:
            print(f"Error al conectar a MongoDB: {e}")
            exit()   

        self.usuarios = self.db.usuarios
        self.biblioteca_personal = self.db.biblioteca_personal
        self.lista_lectura = self.db.lista_lectura
        
        self.GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
        
    async def buscar_libro_google(self, query):
        params = {
            'q': query,
            'maxResults': 3, 
            'langRestrict': 'es' 
        }
        
        try:
            response = requests.get(self.GOOGLE_BOOKS_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'items' not in data:
                return []
                
            libros = []
            for item in data['items']:
                info = item['volumeInfo']
                libro = {
                    'titulo': info.get('title', 'Sin título'),
                    'autor': ', '.join(info.get('authors', ['Autor desconocido'])),
                    'descripcion': info.get('description', 'Sin descripción'),
                    'categorias': info.get('categories', []),
                    'imagen': info.get('imageLinks', {}).get('thumbnail', None),
                    'id_google': item['id'],
                    'fecha_publicacion': info.get('publishedDate', 'Fecha desconocida'),
                    'isbn': next((id['identifier'] for id in info.get('industryIdentifiers', []) 
                                if id['type'] == 'ISBN_13'), None)
                }
                libros.append(libro)
            return libros
        except requests.RequestException as e:
            print(f"Error al buscar en Google Books: {e}")
            return []

    def get_libro_detalles(self, libro_id):
        url = f"https://www.googleapis.com/books/v1/volumes/{libro_id}"
        response = requests.get(url)
        if response.status_code == 200:
            libro = response.json()
            detalles = {
                'titulo': libro.get('volumeInfo', {}).get('title', 'Sin título'),
                'autor': ', '.join(libro.get('volumeInfo', {}).get('authors', ['Sin autor'])),
                'anio': libro.get('volumeInfo', {}).get('publishedDate', 'Sin año'),
                'descripcion': libro.get('volumeInfo', {}).get('description', 'Sin descripción disponible')
            }
            return detalles
        else:
            return None     

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if not self.usuarios.find_one({"user_id": user_id}):
            self.usuarios.insert_one({
                "user_id": user_id,
                "username": update.effective_user.username,
                "created_at": datetime.now()
            })

        keyboard = [
            [InlineKeyboardButton("📚 Buscar Libro", callback_data='buscar_libro')],
            [InlineKeyboardButton("📖 Mi Biblioteca", callback_data='mi_biblioteca')],
            [InlineKeyboardButton("📝 Lista de Lectura", callback_data='lista_lectura')],
            [InlineKeyboardButton("📊 Mis Estadísticas", callback_data='estadisticas')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        query = update.callback_query
        if query:
            await query.answer()  
            await query.message.edit_text(
                f"¡Hola {update.effective_user.first_name or 'lector'}! 👋\n"
                "📚 Bienvenido a tu Biblioteca Personal.\n\n"
                "Aquí puedes gestionar tus libros favoritos, llevar un seguimiento de tus lecturas y descubrir nuevas obras. 🥳\n"
                "¿Qué te gustaría hacer hoy?",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"¡Hola {update.effective_user.first_name or 'lector'}! 👋\n"
                "📚 Bienvenido a tu Biblioteca Personal.\n\n"
                "Aquí puedes gestionar tus libros favoritos, llevar un seguimiento de tus lecturas y descubrir nuevas obras. 🥳\n"
                "¿Qué te gustaría hacer hoy?",
                reply_markup=reply_markup
            )

    async def buscar_libro(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.message.reply_text(
            "Por favor, escribe el título o autor del libro que quieres buscar:"
        )
        return 'esperando_busqueda'

    async def procesar_busqueda(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.message.text
        libros = await self.buscar_libro_google(query)
        
        if not libros:
            await update.message.reply_text(
                "😔 No encontramos libros que coincidan con tu búsqueda.\n"
                "📌 Consejo: Prueba con otro título, autor o palabras clave.\n"
                "¡No te rindas, seguro encuentras algo genial!"
            )
            return ConversationHandler.END
            
        for libro in libros:
            texto = (
                f"📖 {libro['titulo']}\n"
                f"✍️ {libro['autor']}\n"
                f"📅 {libro['fecha_publicacion']}\n\n"
                f"📝 {libro['descripcion'][:200]}...\n"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("➕ Agregar a Biblioteca", 
                                       callback_data=f"add_biblioteca_{libro['id_google']}"),
                    InlineKeyboardButton("📝 Agregar a Lista de Lectura", 
                                       callback_data=f"add_lista_{libro['id_google']}")
                ]
            ]

            keyboard.append([InlineKeyboardButton("🔙 Volver al inicio", callback_data='start')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(texto, reply_markup=reply_markup)
            
        return ConversationHandler.END

    async def agregar_a_biblioteca(self, update: Update, context: ContextTypes.DEFAULT_TYPE):

        query = update.callback_query
        await query.answer()
        libro_id = query.data.split('_')[2]
        user_id = update.effective_user.id
        
        if self.biblioteca_personal.find_one({"user_id": user_id, "google_id": libro_id}):
            await query.message.reply_text(
            "📚 Este libro ya está en tu biblioteca. No es necesario agregarlo de nuevo."
            )
            return
        
        try:
            params = {'id': libro_id}
            response = requests.get(f"{self.GOOGLE_BOOKS_URL}/{libro_id}")
            libro_info = response.json()['volumeInfo']
        except requests.RequestException:
            await query.message.reply_text("⚠️ Hubo un problema al obtener la información del libro.")
            return

        
        libro = {
            "user_id": user_id,
            "google_id": libro_id,
            "titulo": libro_info.get('title'),
            "autor": ', '.join(libro_info.get('authors', [])),
            "fecha_agregado": datetime.now(),
        }

        self.biblioteca_personal.insert_one(libro)

        texto = (
            f"🎉 ¡Genial! '{libro_info.get('title', 'Sin título')}' ahora forma parte de tu biblioteca.\n"
            "📖 ¿Qué tal si lo calificas?\n"
        )

        botones = [
            [
                InlineKeyboardButton("⭐ Clasificar este libro", callback_data=f"calificar_biblioteca_{libro_id}"),
                InlineKeyboardButton("🔙 Volver al inicio", callback_data="start")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(botones)      
        await query.edit_message_text(texto, reply_markup=reply_markup)

    async def mostrar_biblioteca(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        libros = list(self.biblioteca_personal.find({"user_id": user_id}))

        if not libros:
            await update.callback_query.message.reply_text(
                "Tu biblioteca está vacía. ¡Empieza a agregar libros!",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Volver al inicio", callback_data='start')]]
                )
            )         
            return

        for libro in libros:
            texto = (
                f"📖 {libro['titulo']}\n"
                f"✍️ {libro['autor']}\n"
                f"📅 Agregado el: {libro['fecha_agregado'].strftime('%d-%m-%Y')}\n"
                f"⭐ Calificación: {libro.get('rating', 'Sin calificar')}\n"
            )
        
            keyboard = [
                [
                    InlineKeyboardButton("📖 Ver Detalles", callback_data=f"detalles_biblioteca_{libro['google_id']}"),
                    InlineKeyboardButton("❌ Eliminar", callback_data=f"eliminar_biblioteca_{libro['google_id']}")
                ],
                [
                InlineKeyboardButton("⭐ Calificar", callback_data=f"calificar_biblioteca_{libro['google_id']}")
            ]
            ]

            keyboard.append([InlineKeyboardButton("🔙 Volver al inicio", callback_data='start')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.callback_query.message.reply_text(texto, reply_markup=reply_markup)
            

    async def detalles_libro_biblioteca(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        libro_id = query.data.split('_')[2]
        detalles = self.get_libro_detalles(libro_id)

        if detalles:
            mensaje = (
                f"*Título:* {detalles['titulo']}\n"
                f"*Autor:* {detalles['autor']}\n"
                f"*Año de publicación:* {detalles['anio']}\n"
                f"*Descripción:* {detalles['descripcion']}\n"
            )
        else:
            mensaje = "No se pudieron obtener los detalles del libro."

        await query.message.reply_text(mensaje, parse_mode="Markdown")

    async def eliminar_de_biblioteca(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        libro_id = query.data.split('_')[2]
        user_id = update.effective_user.id

        self.biblioteca_personal.delete_one({"user_id": user_id, "google_id": libro_id})
        await query.message.reply_text(
            "El libro ha sido eliminado de tu biblioteca. 🗑️\n"
            "¡Espero encuentres algo mejor para leer pronto! 📚"
        )               

    async def calificar_libro(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        libros = list(self.biblioteca_personal.find({"user_id": user_id}))

        if not libros:
            await update.callback_query.message.reply_text("Tu biblioteca está vacía. Agrega algunos libros primero.")
            return
        
        keyboard = [
            [InlineKeyboardButton(libro["titulo"], callback_data=f"rate_{libro['_id']}")]
            for libro in libros
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.message.reply_text(
            "Selecciona el libro que deseas calificar:", reply_markup=reply_markup
        )

    async def solicitar_calificacion(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        libro_id = query.data.split('_')[2]
        context.user_data['libro_calificar'] = libro_id

        keyboard = [
            [InlineKeyboardButton("1 ⭐", callback_data="calificacion_1"),
            InlineKeyboardButton("2 ⭐⭐", callback_data="calificacion_2")],
            [InlineKeyboardButton("3 ⭐⭐⭐", callback_data="calificacion_3"),
            InlineKeyboardButton("4 ⭐⭐⭐⭐", callback_data="calificacion_4")],
            [InlineKeyboardButton("5 ⭐⭐⭐⭐⭐", callback_data="calificacion_5"),
            InlineKeyboardButton("6 ⭐⭐⭐⭐⭐⭐", callback_data="calificacion_6")],
            [InlineKeyboardButton("7 ⭐⭐⭐⭐⭐⭐⭐", callback_data="calificacion_7"),
            InlineKeyboardButton("8 ⭐⭐⭐⭐⭐⭐⭐⭐", callback_data="calificacion_8")],
            [InlineKeyboardButton("9 ⭐⭐⭐⭐⭐⭐⭐⭐⭐", callback_data="calificacion_9"),
            InlineKeyboardButton("10 ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐", callback_data="calificacion_10")]
        ]

        keyboard.append([InlineKeyboardButton("🔙 Volver al inicio", callback_data='start')])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Selecciona una calificación para este libro:", reply_markup=reply_markup)

    async def guardar_calificacion(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        calificacion = int(query.data.split('_')[1])
        user_id = update.effective_user.id
        libro_id = context.user_data.get('libro_calificar')

        if not libro_id:
            await query.message.reply_text("No se pudo identificar el libro a calificar. Inténtalo nuevamente.")
            return

        self.biblioteca_personal.update_one(
            {"user_id": user_id, "google_id": libro_id},
            {"$set": {"rating": calificacion}}
        )
        await query.message.reply_text(f"Gracias por calificar el libro con {calificacion} ⭐.")            


    async def agregar_a_lista_lectura(self, update: Update, context: ContextTypes.DEFAULT_TYPE):

        query = update.callback_query
        await query.answer()

        libro_id = query.data.split('_')[2]
        user_id = update.effective_user.id
        

        if self.lista_lectura.find_one({"user_id": user_id, "google_id": libro_id}):
            await query.message.reply_text(
                "📝 Este libro ya está en tu lista de lectura. ¡Échale un vistazo!"
            )
            return

        try:
            response = requests.get(f"{self.GOOGLE_BOOKS_URL}/{libro_id}")
            response.raise_for_status()
            libro_info = response.json()['volumeInfo']
        except requests.RequestException:
            await query.edit_message_text("⚠️ Hubo un problema al obtener la información del libro.")
            return     
    
        libro = {
                "user_id": user_id,
                "google_id": libro_id,
                "titulo": libro_info.get('title', 'Sin título'),
                "autor": ', '.join(libro_info.get('authors', [])),
                "fecha_agregado": datetime.now(),
                "estado": "pendiente"
        }
            
        self.lista_lectura.insert_one(libro)

        texto = (
            f"🎉 El libro '{libro_info.get('title', 'Sin título')}' ha sido agregado a tu lista de lectura. ¡Disfrútalo pronto!\n"
        )

        botones = [
            [
                InlineKeyboardButton("🔙 Volver al inicio", callback_data="start")
            ]
        ]
        teclado = InlineKeyboardMarkup(botones)
        await query.message.reply_text(texto, reply_markup=teclado)
           
    async def mostrar_lista_lectura(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    
        user_id = update.effective_user.id
        libros = list(self.lista_lectura.find({"user_id": user_id}))
    
        if not libros:
            await update.callback_query.message.reply_text(
                "Tu lista de lectura está vacía. ¡Empieza a agregar libros!",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Volver al inicio", callback_data='start')]]
                )
            )
            return
    
        for libro in libros:
            texto = (
                f"📖 {libro['titulo']}\n"
                f"✍️ {libro['autor']}\n"
                f"📅 Agregado el: {libro['fecha_agregado'].strftime('%d-%m-%Y')}\n"
            )
        
            keyboard = [
                [
                    InlineKeyboardButton("✅ Marcar como leído", 
                                        callback_data=f"marcar_leido_{libro['google_id']}"),
                    InlineKeyboardButton("❌ Eliminar", 
                                        callback_data=f"eliminar_lista_{libro['google_id']}")
                ]
            ]

            keyboard.append([InlineKeyboardButton("🔙 Volver al inicio", callback_data='start')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.callback_query.message.reply_text(texto, reply_markup=reply_markup)

    async def marcar_como_leido(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        libro_id = query.data.split('_')[2]
        user_id = update.effective_user.id
    
   
        libro = self.lista_lectura.find_one({"user_id": user_id, "google_id": libro_id})
        if not libro:
            await query.message.reply_text("El libro no se encontró en tu lista de lectura.")
            return
    
        libro["estado"] = "leído"
        libro["fecha_leido"] = datetime.now()
        self.biblioteca_personal.insert_one(libro)
        
        self.lista_lectura.delete_one({"user_id": user_id, "google_id": libro_id})

        await query.message.reply_text(
            f"🎉 ¡Felicidades por terminar '{libro['titulo']}'! 👏. Ha sido marcado como leído y agregado a tu biblioteca.\n"
            "Te invito a que lo clasifiques para recordarlo mejor 😊"
        )
        

    async def eliminar_de_lista(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        libro_id = query.data.split('_')[2]
        user_id = update.effective_user.id
    
        self.lista_lectura.delete_one({"user_id": user_id, "google_id": libro_id})
    
        await query.message.reply_text("El libro ha sido eliminado de tu lista de lectura. 🗑️\n"
        "¡Espero encuentres algo mejor para leer pronto! 📚"
        )
     
     


    async def mostrar_estadisticas(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        libros = list(self.biblioteca_personal.find({"user_id": user_id}))
        libros_lista_lectura = list(self.lista_lectura.find({"user_id": user_id}))
        libros_pendientes = len(libros_lista_lectura)
        promedio_calificacion = sum(l.get('rating', 0) for l in libros) / len(libros) if libros else 0
        
        generos = {}
        for libro in libros:
            categorias = libro.get('categorias', [])
            if isinstance(categorias, list):
                for genero in categorias:
                    generos[genero] = generos.get(genero, 0) + 1
        
        top_generos = sorted(generos.items(), key=lambda x: x[1], reverse=True)[:3]
        
        mensaje = (
            "📊 Tus Estadísticas de Lectura:\n\n"
            f"📚 Total de libros: {len(libros)}\n"
            f"📖 Libros pendientes: {libros_pendientes}\n"
            f"⭐ Calificación promedio: {promedio_calificacion:.1f}/10\n\n"
            "📘 Géneros favoritos:\n"
        )
        
        if top_generos:
            for genero, cantidad in top_generos:
                mensaje += f"- 📚 *{genero}*: {cantidad} libros\n"
        else:
            mensaje += "No se han registrado géneros.\n"

        mensaje += "\n🚀 ¡Sigue así! Cada libro leído es un paso más hacia un mundo de conocimiento y aventuras. 🚀"

        keyboard = [[InlineKeyboardButton("🔙 Volver al inicio", callback_data='start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.message.edit_text(mensaje, reply_markup=reply_markup)


if __name__ == '__main__':

    TOKEN = 'BOT DE TOKEN ACA'
    bot = CapituloCeroBot(TOKEN)

    # Configuracion de handlers
    application = Application.builder().token(TOKEN).build()
    
    # Handler para búsqueda de libros
    conv_handler_busqueda = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.buscar_libro, pattern='^buscar_libro$')],
        states={
            'esperando_busqueda': [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.procesar_busqueda)]
        },
        fallbacks=[]
    )

    conv_handler_calificacion = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.calificar_libro, pattern='^calificar_libro$')],
        states={
            'esperando_calificacion': [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.guardar_calificacion)],
        },
        fallbacks=[]
    )

    
    # Start
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CallbackQueryHandler(bot.start, pattern='^start$'))
    application.add_handler(CommandHandler("biblioteca", bot.mostrar_biblioteca))

    # Conversation para búsquedas
    application.add_handler(conv_handler_busqueda)

    # Callbacks para agregar libros y gestionar la biblioteca
    application.add_handler(CallbackQueryHandler(bot.mostrar_biblioteca, pattern='^mi_biblioteca$'))
    application.add_handler(CallbackQueryHandler(bot.agregar_a_biblioteca, pattern='^add_biblioteca_'))
    application.add_handler(CallbackQueryHandler(bot.eliminar_de_biblioteca, pattern='^eliminar_biblioteca_'))
    application.add_handler(CallbackQueryHandler(bot.detalles_libro_biblioteca, pattern='^detalles_biblioteca_'))
    application.add_handler(CallbackQueryHandler(bot.agregar_a_lista_lectura, pattern='^add_lista_'))
    application.add_handler(CallbackQueryHandler(bot.mostrar_lista_lectura, pattern='^lista_lectura$'))
    application.add_handler(CallbackQueryHandler(bot.marcar_como_leido, pattern='^marcar_leido_'))
    application.add_handler(CallbackQueryHandler(bot.eliminar_de_lista, pattern='^eliminar_lista_'))

    # Estadísticas
    application.add_handler(CallbackQueryHandler(bot.mostrar_estadisticas, pattern='^estadisticas$'))

    # Calificaciones
    application.add_handler(CallbackQueryHandler(bot.solicitar_calificacion, pattern='^calificar_biblioteca_'))
    application.add_handler(CallbackQueryHandler(bot.guardar_calificacion, pattern='^calificacion_'))
    application.add_handler(CallbackQueryHandler(bot.calificar_libro, pattern='^calificar_libro$'))
    application.add_handler(CallbackQueryHandler(bot.solicitar_calificacion, pattern='^rate_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.guardar_calificacion))
    
    # Iniciar el bot
    print("Bot iniciado")
    application.run_polling()