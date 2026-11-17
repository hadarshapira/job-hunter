FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY public-site /usr/share/nginx/public
# Contact address on the public home + privacy pages (CONTACT_EMAIL in .env)
ARG CONTACT_EMAIL=
RUN sed -i "s|__CONTACT_EMAIL__|${CONTACT_EMAIL:-the owner of this copy}|g; s|mailto:the owner of this copy|#|g" /usr/share/nginx/public/*.html
