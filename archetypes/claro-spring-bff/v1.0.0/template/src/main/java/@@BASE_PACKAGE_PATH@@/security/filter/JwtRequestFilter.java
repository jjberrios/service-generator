package @@BASE_PACKAGE@@.security.filter;

import io.jsonwebtoken.Claims;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// ...existing code...
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;

import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import @@BASE_PACKAGE@@.security.service.JwtValidatorService;

import java.io.IOException;
import java.util.Collection;
import java.util.List;
import java.util.stream.Collectors;


/**
 * Filtro que intercepta todas las peticiones para validar el token JWT.
 * Extiende de OncePerRequestFilter para asegurar que se ejecuta solo una vez por petición.
 */
@Component
public class JwtRequestFilter extends OncePerRequestFilter {

    private static final Logger F_LOGGER = LoggerFactory.getLogger(JwtRequestFilter.class);

    private final JwtValidatorService jwtValidatorService;
    public JwtRequestFilter(JwtValidatorService jwtValidatorService) {
        this.jwtValidatorService = jwtValidatorService;
    }



    public static final String AUTHORIZATION_HEADER = "Authorization";
    public static final String BEARER_PREFIX = "Bearer ";

    @Override
        protected void doFilterInternal(
            @org.springframework.lang.NonNull HttpServletRequest request,
            @org.springframework.lang.NonNull HttpServletResponse response,
            @org.springframework.lang.NonNull FilterChain filterChain)
            throws ServletException, IOException {
        try {
            String jwt = extractJwtFromRequest(request);

            if (StringUtils.hasText(jwt) && jwtValidatorService.validateToken(jwt)) {

                
                Claims claims = jwtValidatorService.getClaimsFromToken(jwt);
                
                
                String username = claims.getSubject();

                
                @SuppressWarnings("unchecked")
                List<String> roles = claims.get("roles", List.class);

                Collection<GrantedAuthority> authorities = roles.stream()
                        .map(SimpleGrantedAuthority::new)
                        .collect(Collectors.toList());

                

                
                UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(
                        username,
                        null,
                        authorities
                );

                authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));

                
                SecurityContextHolder.getContext().setAuthentication(authentication);
            }
        } catch (Exception e) {
            F_LOGGER.error("No se pudo establecer la autenticación del usuario: {}", e.getMessage());
        }

        filterChain.doFilter(request, response);
    }

    /**
     * Helper para extraer el token del "Authorization Header".
     */
    private String extractJwtFromRequest(HttpServletRequest request) {
        String bearerToken = request.getHeader(AUTHORIZATION_HEADER);
        if (StringUtils.hasText(bearerToken) && bearerToken.startsWith(BEARER_PREFIX)) {
            return bearerToken.substring(BEARER_PREFIX.length());
        }
        return null;
    }
}
