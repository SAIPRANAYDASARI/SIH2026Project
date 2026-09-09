# syntax=docker/dockerfile:1
FROM node:22-slim AS base
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app

# --- dev stage: Vite dev server with HMR ------------------------------------
FROM base AS development
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
USER app
EXPOSE 5173
CMD ["npm", "run", "dev"]

# --- build stage -------------------------------------------------------------
FROM base AS build
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# --- production stage: static files served by Nginx (see infra/nginx) ------
FROM nginx:1.27-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
