# Web UI — কোনো build ধাপ নেই। nginx শুধু public/ এর ফাইলগুলো দেয়
# আর /api/... রিকোয়েস্ট backend এ পাঠায় (nginx.conf দেখো)।
FROM nginx:1.30-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY public /usr/share/nginx/html

EXPOSE 80
