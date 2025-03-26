## Foodgram
«Фудграм» — сайт, на котором пользователи могут публиковать свои рецепты, добавлять чужие в избранное и подписываться на публикации других авторов. Зарегистрированным пользователям также будет доступен сервис «Список покупок». Он позволит создавать список продуктов, которые нужно купить для приготовления выбранных блюд.

## Для запуска проекта:

#### Клонируем репозиторий: 
https://github.com/sergey9295/foodgram-st

#### Создаём в директории backend/foodgram файл .env и заполняем его:
- DEBUG=True
- ALLOWED_HOSTS=localhost,127.0.0.1
- USE_SQLITE=False
- DB_ENGINE=django.db.backends.postgresql
- DB_NAME=foodgram
- DB_USER=foodgram_user
- DB_PASSWORD=foodgram_password
- DB_HOST=postgres
- DB_PORT=5432

#### Переходим в папку infra: 
cd .\infra\

#### Запускаем docker-compose: 
docker-compose up -d 

#### Миграции выполняются автоматически (команды прописаны в backend/Dockerfile)
