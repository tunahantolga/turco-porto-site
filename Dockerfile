FROM nginx:1.27-alpine

# Listens on $PORT if the platform sets one, otherwise 8080 (Outplane default).
ENV PORT=8080

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html
COPY images /usr/share/nginx/html/images
COPY favicon.ico robots.txt sitemap.xml site.webmanifest llms.txt /usr/share/nginx/html/

EXPOSE 8080
