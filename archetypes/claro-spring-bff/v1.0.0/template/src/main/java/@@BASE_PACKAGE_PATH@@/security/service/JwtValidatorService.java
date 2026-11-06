package @@BASE_PACKAGE@@.security.service;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.security.SignatureException;

/**
 * Define el contrato de servicios de validación para tokens JWT utilizados en
 * los flujos de autenticación e integración del microservicio.
 * <p>
 * Centraliza las operaciones de verificación de firma, expiración y extracción
 * de claims, de acuerdo con las políticas de seguridad corporativas.
 * </p>
 */
public interface JwtValidatorService {

    /**
     * Valida un token JWT verificando su estructura, firma y vigencia de
     * acuerdo con la configuración de seguridad establecida.
     *
     * @param token token JWT recibido en la cabecera de autorización de la
     *              solicitud
     * @return {@code true} si el token es válido conforme a las políticas de
     *         seguridad; {@code false} en caso contrario
     */
    public boolean validateToken(String token);

    /**
     * Obtiene los claims contenidos en un token JWT previamente validado.
     *
     * @param token token JWT desde el cual se extraerán los claims
     * @return objeto {@link Claims} con la información declarativa contenida en
     *         el token
     * @throws ExpiredJwtException si el token se encuentra expirado
     * @throws SignatureException  si la firma del token no es válida o ha
     *                             sido alterada
     */
    public Claims getClaimsFromToken(String token) throws ExpiredJwtException, SignatureException;
}
