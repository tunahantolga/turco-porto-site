FROM nginx:1.27-alpine

# Listens on $PORT if the platform sets one, otherwise 80.
ENV PORT=80

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html
COPY images /usr/share/nginx/html/images

EXPOSE 80
