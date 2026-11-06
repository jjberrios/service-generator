package @@BASE_PACKAGE@@.security.service.impl;


import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.Jws;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.MalformedJwtException;
import io.jsonwebtoken.UnsupportedJwtException;
import io.jsonwebtoken.security.Keys;
import io.jsonwebtoken.security.SignatureException;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import @@BASE_PACKAGE@@.security.service.JwtValidatorService;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;

/**
 * Componente de Spring para validar tokens JWT.
 * Maneja la validación de la firma y la expiración del token.
 */
@Component
public class JwtValidatorServiceImpl implements JwtValidatorService {

    private static final Logger JWTVALIDATIONLOGGER = LoggerFactory.getLogger(JwtValidatorServiceImpl.class);

    
    @Value("${security.jwt.secret-key}")
    private String jwtSecretString;

    private JwtParser jwtParser;

    /**
     * PostConstruct se ejecuta después de la inyección de dependencias
     * (cuando jwtSecretString ya tiene su valor).
     */
    @PostConstruct
    public void init() {
        
        SecretKey secretKey = Keys.hmacShaKeyFor(jwtSecretString.getBytes(StandardCharsets.UTF_8));
        this.jwtParser = Jwts.parserBuilder()
            .setSigningKey(secretKey)
            .build();
    }

    /**
     * Valida un token JWT.
     *
     * @param token El string del JWT (sin el prefijo "Bearer ").
     * @return true si el token es válido (firma correcta Y no expirado), false en caso contrario.
     */
    public boolean validateToken(String token) {
        try {
            
            jwtParser.parseClaimsJws(token);
            return true;
            
        } catch (SignatureException e) {
            JWTVALIDATIONLOGGER.error("Error de validación JWT: Firma inválida -> {}", e.getMessage());
        } catch (MalformedJwtException e) {
            JWTVALIDATIONLOGGER.error("Error de validación JWT: Token malformado -> {}", e.getMessage());
        
        } catch (UnsupportedJwtException e) {
            JWTVALIDATIONLOGGER.error("Error de validación JWT: Token no soportado -> {}", e.getMessage());
        } catch (IllegalArgumentException e) {
            JWTVALIDATIONLOGGER.error("Error de validación JWT: Claims vacíos -> {}", e.getMessage());
        }

        return false;
    }

    /**
     * Método de utilidad (opcional) para obtener los "claims" si el token es válido.
     * Si la validación falla (ej. expirado), lanzará la excepción correspondiente.
     *
     * @param token El string del JWT.
     * @return El objeto Claims que contiene (subject, roles, etc.)
     * @throws ExpiredJwtException Si el token está expirado.
     * @throws SignatureException Si la firma es incorrecta.
     */
    public Claims getClaimsFromToken(String token) throws ExpiredJwtException, SignatureException {
        Jws<Claims> jwsClaims = jwtParser.parseClaimsJws(token);
        return jwsClaims.getBody();
    }
}
