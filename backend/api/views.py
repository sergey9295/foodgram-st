import base64
import csv
import os
import uuid
from io import StringIO
from fpdf import FPDF

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import redirect
from django_filters.rest_framework import DjangoFilterBackend
from djoser.views import UserViewSet as DjoserUserViewSet
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from api.abstractions.views import manage_user_recipe
from api.fields import Base62Field
from api.filters import RecipeFilter
from api.paginations import Pagination
from api.permissions import IsAuthorOrReadOnly
from api.serializers import (FavoriteSerializer, FollowSerializer,
                             IngredientSerializer, RecipeReadSerializer,
                             RecipeWriteSerializer, ShoppingCartSerializer,
                             SubscriptionSerializer, UserSerializer)
from recipes.models import (Favorite, Ingredient, Recipe, RecipeIngredient,
                            ShoppingCart)
from users.models import Follow

User = get_user_model()


class UserViewSet(DjoserUserViewSet):
    queryset = User.objects.all().order_by('username')
    serializer_class = UserSerializer
    pagination_class = Pagination
    permission_classes = [permissions.AllowAny]

    @action(detail=False,
            methods=['get'],
            permission_classes=[permissions.IsAuthenticated]
            )
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False,
            methods=['put', 'delete'],
            permission_classes=[permissions.IsAuthenticated],
            url_path='me/avatar'
            )
    def avatar(self, request):
        user = request.user

        if request.method == 'PUT':
            avatar_data = request.data.get('avatar')

            if not avatar_data:
                return Response(
                    {"avatar": ["Это поле обязательно."]},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                if user.avatar:
                    user.avatar.delete()

                format, imgstr = avatar_data.split(';base64,')
                ext = format.split('/')[-1]
                data = ContentFile(base64.b64decode(imgstr),
                                   name=f"{uuid.uuid4()}.{ext}")

                user.avatar.save(data.name, data, save=True)
                user.save()

                avatar_url = request.build_absolute_uri(user.avatar.url)

                return Response({"avatar": avatar_url},
                                status=status.HTTP_200_OK)

            except Exception as e:
                return Response(
                    {"error": str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )

        if user.avatar:
            avatar_path = user.avatar.path
            if os.path.exists(avatar_path):
                os.remove(avatar_path)
            user.avatar.delete()
            user.avatar = None
            user.save()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            {"detail": "Аватар отсутствует."},
            status=status.HTTP_404_NOT_FOUND
        )

    @action(detail=True,
            methods=['post', 'delete'],
            url_path='subscribe',
            permission_classes=[permissions.IsAuthenticated]
            )
    def manage_subscription(self, request, id=None):
        user = request.user

        if request.method == 'POST':
            serializer = SubscriptionSerializer(
                data={'following_id': id},
                context={'request': request}
            )

            serializer.is_valid(raise_exception=True)
            follow = serializer.save()
            return Response(
                FollowSerializer(
                    follow.following,
                    context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )

        following_user = get_object_or_404(User, pk=id)

        follow_instance = Follow.objects.filter(
            user=user, following=following_user).first()

        if not follow_instance:
            return Response(
                {"detail": "Вы не подписаны на этого пользователя."},
                status=status.HTTP_400_BAD_REQUEST
            )

        follow_instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False,
            methods=['get'],
            url_path='subscriptions',
            permission_classes=[permissions.IsAuthenticated]
            )
    def get_subscriptions(self, request):
        user = request.user

        subscriptions = User.objects.filter(following__user=user)

        page = self.paginate_queryset(subscriptions)

        serializer = FollowSerializer(
            page, many=True, context={'request': request})
        return self.get_paginated_response(serializer.data)


class RecipeViewSet(viewsets.ModelViewSet):
    queryset = Recipe.objects.all().select_related(
        'author').prefetch_related('ingredients')
    permission_classes = [
        permissions.IsAuthenticatedOrReadOnly,
        IsAuthorOrReadOnly
    ]
    pagination_class = Pagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = RecipeFilter

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return RecipeWriteSerializer
        return RecipeReadSerializer

    @action(
        detail=True,
        methods=["get"],
        url_path="get-link",
        permission_classes=[permissions.AllowAny]
    )
    def get_link(self, request, pk=None):
        recipe = self.get_object()

        short_code = Base62Field.to_base62(recipe.id)

        short_link = request.build_absolute_uri(f"/s/{short_code}")

        return Response({"short-link": short_link}, status=status.HTTP_200_OK)

    def redirect_to_recipe(self, request, short_code=None):
        try:
            recipe_id = Base62Field.from_base62(short_code)
        except ValueError:
            return Response(
                {"detail": "Неверный короткий код."},
                status=status.HTTP_400_BAD_REQUEST
            )

        recipe = get_object_or_404(Recipe, id=recipe_id)
        redirect_url = request.build_absolute_uri(f"/recipes/{recipe.id}/")
        return redirect(redirect_url)

    @action(detail=False,
            methods=['get'],
            url_path='download_shopping_cart',
            permission_classes=[permissions.IsAuthenticated]
            )
    def get_ingredients_list_from_cart(self, user):
        ingredients = (
            RecipeIngredient.objects
            .filter(recipe__shopping_carts__user=user)
            .values('ingredient__name', 'ingredient__measurement_unit')
            .annotate(amount=Sum('amount'))
            .order_by('ingredient__name')
        )

        ingredients_list = [
            {
                'name': ingredient['ingredient__name'],
                'amount': ingredient['amount'],
                'measurement_unit': ingredient['ingredient__measurement_unit']
            }
            for ingredient in ingredients
        ]

        return ingredients_list

    @action(detail=False,
            methods=['get'],
            url_path='download_shopping_cart',
            permission_classes=[permissions.IsAuthenticated])
    def download_shopping_cart(self, request):
        ingredients_list = self.get_ingredients_list_from_cart(request.user)

        file_format = request.query_params.get('format', 'txt').lower()

        format_functions = {
            'txt': self.generate_txt_file,
            'csv': self.generate_csv_file,
            'pdf': self.generate_pdf_file
        }

        generate_function = format_functions.get(file_format)

        if generate_function:
            return generate_function(ingredients_list)
        else:
            return Response(
                {"detail": "Выбран неверный формат файла"},
                status=status.HTTP_400_BAD_REQUEST
            )

    def generate_txt_file(self, ingredients):
        content = "\n".join(
            [
                f"{ingredient['name']} ({ingredient['measurement_unit']}) — "
                f"{ingredient['amount']}"
                  for ingredient in ingredients
            ]
        )
        response = HttpResponse(content, content_type="text/plain")
        response['Content-Disposition'] = (
            'attachment; filename="shopping_cart.txt"'
        )
        return response

    def generate_csv_file(self, ingredients):
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Ингредиент', 'Количество',
                        'Единица измерения'])
        for ingredient in ingredients:
            writer.writerow(
                [
                    ingredient['name'],
                    ingredient['amount'],
                    ingredient['measurement_unit']
                ]
            )

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response['Content-Disposition'] = (
            'attachment; filename="shopping_cart.csv"'
        )
        return response

    def generate_pdf_file(self, ingredients):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        pdf.cell(200, 10, txt="Список покупок", ln=True, align='C')

        for ingredient in ingredients:
            pdf.cell(
                200,
                10,
                txt=(
                    f"{ingredient['name']} "
                    f"({ingredient['measurement_unit']}) — "
                    f"{ingredient['amount']}"
                ),
                ln=True)

        response = HttpResponse(pdf.output(dest='S').encode(
            'latin1'), content_type='application/pdf')
        response['Content-Disposition'] = (
            'attachment; filename="shopping_cart.pdf"'
        )
        return response


    @action(
        detail=True,
        methods=['post', 'delete'],
        url_path='favorite',
        permission_classes=[permissions.IsAuthenticated]
    )
    def manage_favorite(self, request, pk=None):
        return manage_user_recipe(
            request,
            pk,
            Favorite,
            FavoriteSerializer
        )

    @action(
        detail=True,
        methods=['post', 'delete'],
        url_path='shopping_cart',
        permission_classes=[permissions.IsAuthenticated]
    )
    @action(
        detail=True,
        methods=['post', 'delete'],
        url_path='shopping_cart',
        permission_classes=[permissions.IsAuthenticated]
    )
    def manage_shopping_cart(self, request, pk=None):
        return manage_user_recipe(
            request,
            pk,
            ShoppingCart,
            ShoppingCartSerializer
        )


class IngredientViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer
    filter_backends = (SearchFilter,)
    search_fields = ['name']
    pagination_class = None

    def get_queryset(self):
        queryset = super().get_queryset()
        name = self.request.query_params.get('name', None)
        if name:
            queryset = queryset.filter(name__istartswith=name)
        return queryset
