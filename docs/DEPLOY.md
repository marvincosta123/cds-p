# Implantação e monitoramento

## Variáveis de ambiente
| Variável | Função |
|---|---|
| `DJANGO_SECRET_KEY` | chave secreta (longa e aleatória; nunca no repositório) |
| `DJANGO_DEBUG` | `0` em produção |
| `DJANGO_ALLOWED_HOSTS` | hosts permitidos, separados por vírgula (o Render adiciona o seu automaticamente) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | origens `https://...` confiáveis, se necessário |
| `DJANGO_FORCE_HTTPS` | `1` para redirecionar a HTTPS atrás de proxy |
| `DATABASE_URL` | `postgres://usuario:senha@host:porta/nome` |

## Passo a passo (Render, modelo `render.yaml`)
1. Em render.com, crie uma conta e escolha **New > Blueprint**, apontando para este repositório.
2. Confirme o serviço web `sepala-estoque` e o banco `sepala-db`; confira os limites do plano gratuito.
3. Crie o usuário de acesso sem terminal: defina `DJANGO_SUPERUSER_USERNAME` e `DJANGO_SUPERUSER_PASSWORD`
   (senha só no painel, em Environment) e faça um novo deploy. O build executa
   `createsuperuser --noinput`, que é ignorado nos deploys seguintes se o usuário já existir.
   (O Shell do Render pode não estar disponível no plano gratuito.)
4. Acesse `https://<seu-servico>.onrender.com/saude/`: deve responder `{"status": "ok", "banco": "ok"}`.

## Monitoramento
- Rota pública `/saude/`: consulta o banco e responde 200 (ok) ou 503 (falha).
- Workflow `.github/workflows/monitoramento.yml`: a cada 15 minutos chama `/saude/`. Se falhar, o job fica
  vermelho (status DOWN) e o GitHub avisa por e-mail. Defina a variável de repositório `URL_PRODUCAO`.
- Alternativa externa: um monitor HTTP (por exemplo, UptimeRobot) apontando para `/saude/`.

## Limites conhecidos
- Em planos gratuitos, o serviço pode ser suspenso por inatividade, e o primeiro acesso fica lento.
- Agendamentos do GitHub Actions podem atrasar alguns minutos.
